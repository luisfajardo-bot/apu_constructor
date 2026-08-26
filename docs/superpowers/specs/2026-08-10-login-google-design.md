# Ingresar con la cuenta de Google

Fecha: 2026-08-10

## Problema

Hoy solo se entra con correo + contraseña: un Admin invita, la persona recibe el correo
de Supabase, define su clave en `/definir-clave` y desde ahí usa `signInWithPassword`.
Eso arrastra dos cosas: contraseñas que la gente olvida (el botón *¿Olvidaste tu
contraseña?* existe por eso) y una dependencia del correo transaccional que todavía
está pendiente de configurar (`docs/runbook-correo-resend-smtp.md`).

Con Google no hay clave que definir ni correo que llegue.

## Lo que ya funciona sin tocar nada

`servicio/auth.py` verifica el JWT contra el JWKS de Supabase (`obtener_claims`). El
token que emite Supabase es el mismo venga de contraseña o de Google, así que la
**autenticación** funciona sin cambios en el backend.

Lo que sí cambia es la **puerta**: `resolver_perfil` busca el perfil por `user_id`. Si
Supabase no vincula la identidad de Google al usuario que creó la invitación, la misma
persona llega con un `user_id` nuevo, sin perfil, y recibe 403 *«Usuario no autorizado
(no invitado)»* sin entender por qué.

## Alcance

- Botón **Continuar con Google** en la pantalla de ingreso, además del formulario de
  contraseña, que se queda.
- **Sigue haciendo falta la invitación de un Admin.** El RBAC no cambia: un gmail
  cualquiera se autentica en Supabase y recibe 403.
- Adopción por email: un invitado que entra con Google se queda con su perfil aunque
  Supabase le dé un `user_id` nuevo.

Fuera de alcance: auto-autorizar el dominio `@indugravas.com` (dejaría la app abierta a
todo el dominio, incluida gente que no debería ver costos); otros proveedores; quitar el
login por contraseña; el flujo de invitación, que no cambia.

## Backend: la adopción por email

`servicio/auth.py::resolver_perfil`, un agregado **antes** del bootstrap por
`APU_ADMIN_EMAILS`:

```
perfil = perfiles.get(user_id)
si perfil is None:
    si identidad_verificada(claims)  Y  perfiles.get_por_email(email) tiene EXACTAMENTE UNO  Y  ese perfil está activo:
        perfiles.reasignar_user_id(viejo_user_id, user_id)
        auditoría "usuario.vincular_identidad"
        seguir por el camino normal (relee el perfil; si estado != activo → ErrorAuth "Usuario inactivo.")
    si no:
        como hoy: bootstrap admin por APU_ADMIN_EMAILS, o ErrorAuth "no invitado"
```

`resolver_perfil` recibe hoy `(alm, user_id, email)`. Necesita un cuarto parámetro
`identidad_verificada: bool` en vez de leer los claims adentro: la función es testeable
sin red justamente porque no sabe de JWTs, y eso se conserva. `usuario_actual` lo saca
de una función pura y testeable, `identidad_verificada(claims)`, que vive en el mismo
`auth.py`.

**Esa función NO lee `claims["user_metadata"]["email_verified"].`** `user_metadata` es
`auth.users.raw_user_meta_data`, y ese bolsillo lo escribe el **propio usuario** con
`supabase.auth.updateUser({ data: {...} })` usando la anon key pública. (`updateUser`
ya está en manos del cliente en esta app: `web/src/pages/DefinirClave.tsx:20` lo llama
con `{ password }`. La forma `{ data }` es la que escribe `user_metadata`, y no hace
falta que la app la use para que cualquiera pueda llamarla con la misma anon key.)
GoTrue no filtra llaves
reservadas dentro de `data`, así que cualquiera puede poner `email_verified: true` en su
propio token con un refresh. Este repo ya tenía escrito como invariante cumplido
*«`user_metadata` nunca usado para authz»* (`docs/auditoria-codigo-2026-07-01.md:125`,
`docs/auditoria-codigo-2026-07-08.md:16`); una versión anterior de este spec lo rompió.

`identidad_verificada(claims)` lee en cambio **solo** claims que pone GoTrue y el
usuario no puede escribir:

- `claims["amr"]`: los métodos de autenticación de ESTA sesión
  (`[{method, timestamp}]`). Señal preferida: `method == "oauth"` para cualquier login
  social, incluido Google.
- `claims["app_metadata"]["provider"/"providers"]`: los proveedores vinculados a la
  cuenta. Solo se cambian con la service_role (nunca desde el cliente). Respaldo si el
  token no trae `amr`.

Fail-closed: si el token no trae ninguna de las dos señales, no se adopta y el Admin lo
arregla a mano.

### Las guardas, cada una por una razón

- **Identidad verificada por un proveedor externo** (no `user_metadata`, ver arriba).
  Sin esto, alguien que se registre con `luisfajardo@indugravas.com` y declare su propio
  `email_verified` se apropia del perfil de Admin.
- **Exactamente un perfil con ese email.** `perfiles.email` **no** es `UNIQUE`
  (`db/seguridad.sql:3`) y la memoria del proyecto ya registra usuarios duplicados en
  producción. Con dos perfiles del mismo correo no se adivina: 403, y lo arregla un
  Admin.
- **El perfil candidato tiene que estar activo.** No re-clava una fila muerta (perfiles
  huérfanos de usuarios borrados en Supabase existen en producción), y así la puerta
  nueva no toca nada en el caso que de todos modos termina denegando.
- **Se re-clava, no se duplica**, y se relee después del `UPDATE` en vez de asumir que
  movió la fila. `user_id` es la PK de `perfiles`; crear un segundo perfil dejaría dos
  filas del mismo correo y descuadraría el guard del último Admin activo (`_GUARD`
  cuenta filas); y si el `UPDATE` movió 0 filas, releer devuelve `None` en vez de un
  `Perfil` fabricado con el rol de otro para una fila que no existe.

El email se compara en minúsculas y sin espacios, igual que `invitar` (`usuarios.py:23`)
y que `config.admin_emails()`.

### Repositorio

`datos/repositorio.py` (Protocol de perfiles), `datos/perfiles_db.py` y
`datos/pg/perfiles_pg.py`:

```python
def get_por_email(self, email: str) -> list[Perfil]: ...        # lista: puede haber 0, 1 o N
def reasignar_user_id(self, viejo: str, nuevo: str, conn=None) -> None: ...
```

Dos métodos tontos; la política ("verificado y exactamente uno") se queda en `auth.py`.
Devolver una lista y no un `Optional` es a propósito: es el repositorio diciendo la
verdad sobre una columna que no es única, en vez de esconder el caso ambiguo.

## Frontend

`web/src/pages/Login.tsx`: un botón **Continuar con Google** debajo del formulario, con
un separador, que llama

```ts
supabase.auth.signInWithOAuth({
  provider: "google",
  options: { redirectTo: `${window.location.origin}/corridas` },
});
```

Nada más: `detectSessionInUrl` viene prendido por defecto en `supabase-js`, canjea el
`?code=` al volver, y el `onAuthStateChange` de `AuthProvider` (`lib/auth.tsx:25`) ya
hace el resto —incluido cerrar sesión y mostrar la pantalla de "no autorizado" si el
backend responde 403—.

El logo va como **SVG inline** (los 4 paths de la marca): `lucide-react` no trae el de
Google y la CSP tiene `img-src 'self' data:`, así que un `<img>` remoto quedaría
bloqueado.

`AuthProvider` no cambia. Se evaluó agregarle un `loginGoogle` al contexto y no vale la
pena: la llamada es una línea contra `supabase` y la página ya importa el cliente para
`resetPasswordForEmail`.

## La CSP no se toca

La ida a `accounts.google.com` es un `window.location.assign` que hace `supabase-js`, y
la CSP no gobierna las navegaciones de primer nivel (`form-action` no aplica: no hay
`<form>`; no tenemos `navigate-to`). El canje del `?code=` es un `fetch` al host de
Supabase, que ya está en `connect-src` (`seguridad_headers.py:20`).

## Pasos manuales (no los hace el código)

Van a `docs/runbook-login-google.md`, con el formato del runbook de Resend:

1. **Google Cloud Console** → APIs & Services → Credentials → OAuth client ID, tipo *Web
   application*:
   - Authorized redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback`
   - Authorized JavaScript origin: `https://armador-apus.onrender.com` (y
     `http://localhost:5173` para desarrollo)
   - La pantalla de consentimiento puede quedar **Internal** si el dominio de Google
     Workspace es el de la empresa: así solo entran cuentas `@indugravas.com` y Google
     hace de primer filtro antes del RBAC.
2. **Supabase** → Authentication → Providers → Google: pegar Client ID y Client Secret,
   habilitar.
3. **Supabase** → Authentication → URL Configuration → Redirect URLs: agregar
   `https://armador-apus.onrender.com/**` y `http://localhost:5173/**`.
4. Smoke test en el navegador, **antes del push** (la lección del `DialogoTexto`
   revertido): entrar con una cuenta invitada, y con una cuenta que no lo esté para
   confirmar el 403 y la pantalla de "no autorizado".

## Pruebas

`tests/test_auth_google.py` (pytest, sin red — inyectando el `Almacen` igual que
`test_auth_rbac.py`, que ya cubre `resolver_perfil`):

- perfil ya existente por `user_id` → se devuelve, sin adopción y sin auditoría (el
  camino de siempre no cambia);
- sin perfil, identidad verificada, **un** perfil activo con ese email → adopta: el
  perfil queda con el `user_id` nuevo, el viejo ya no resuelve, y hay un registro
  `usuario.vincular_identidad`;
- sin perfil, identidad verificada, perfil candidato con `estado='inactivo'` → no
  adopta nada, cae en el mismo `ErrorAuth` "no invitado" de siempre, y el perfil viejo
  queda intacto sin moverse (nunca hubo perfil que "estuviera inactivo" para esa
  sesión: no llegó a resolverse ninguno);
- identidad **no** verificada → `ErrorAuth` "no invitado", y el perfil ajeno queda
  intacto (este es el test de la escalada de privilegios);
- sin perfil, identidad verificada, **dos** perfiles con ese email → `ErrorAuth`, sin
  tocar ninguno;
- identidad verificada que coincide con `APU_ADMIN_EMAILS` y **sin** perfil previo →
  sigue el bootstrap admin de hoy;
- comparación de email insensible a mayúsculas y espacios;
- `identidad_verificada(claims)` como función pura, con dicts de claims falsos: el caso
  central es `{"user_metadata": {"email_verified": True}}` → **False** (el ataque que
  rompía la guarda vieja); además `amr` con método `oauth`/`password`, `app_metadata`
  con `provider`/`providers`, claims vacíos, y formas inesperadas (`amr` que no es
  lista, `app_metadata` en `None`) que no deben reventar;
- `get_por_email` / `reasignar_user_id` dan lo mismo en SQLite y en Postgres: van a
  `tests/test_perfiles_contrato.py`, que ya corre el contrato del repo contra los dos
  backends.

`web/src/pages/Login.test.tsx` (vitest): el botón llama `signInWithOAuth` con
`provider: "google"` y el `redirectTo` del origen actual; el formulario de contraseña
sigue funcionando igual. `Login.a11y.test.tsx`: el botón tiene nombre accesible y el
separador no rompe el orden de foco.

## Riesgo residual

Si Supabase **sí** vincula la identidad (mismo `user_id`), la adopción nunca corre y el
código queda sin ejercitarse en producción. No es motivo para no escribirlo: es
exactamente el caso que deja a un invitado afuera sin explicación, y los tests lo cubren.
