# Runbook — Login con Google (Supabase Auth)

**Objetivo:** que el botón "Continuar con Google" de `/login` funcione en producción, sin
abrir un hueco de seguridad en la adopción de perfiles. Fecha: 2026-08.

---

## Por qué importa (contexto)

- El login de correo+contraseña sigue igual; Google es una **alternativa**, no un
  reemplazo. El acceso lo sigue habilitando la invitación de un Admin — Google solo
  prueba "sos dueño de este correo", no reemplaza la invitación.
- El código ya está completo y en esta rama: repositorio, adopción de perfil por email
  (`apu_tool/servicio/auth.py`) y el botón (`web/src/pages/Login.tsx`). Lo que falta es
  **puramente configuración externa**, en dos consolas que no son este repo: Google
  Cloud Console y el dashboard de Supabase. Sin esos pasos, el botón existe pero el
  login con Google falla (o peor: queda mal configurado y falla en silencio para
  algunos casos).
- Cómo funciona la adopción, en una frase: cuando un invitado entra con Google y
  Supabase le da un `user_id` distinto al que ya tenía su perfil (porque nunca había
  puesto contraseña), el backend re-clava su perfil existente —mismo rol— a ese
  `user_id` nuevo. Pero **solo** si la sesión trae prueba de que un proveedor externo
  (Google) respalda esa identidad; si esa prueba falta, el backend no adivina y deniega.
  Esa prueba es exactamente lo que se verifica más abajo en "Antes de aprobar el merge".

---

## Requisitos previos

- Acceso a **Google Cloud Console** con el proyecto/organización correctos (el
  Workspace de la empresa, si `@indugravas.com` tiene uno).
- Acceso **admin** al proyecto Supabase "BASE APUS".
- Rol **Admin** en la app (para revisar `/usuarios` y `/auditoria` durante la
  verificación).
- ~20 min de trabajo + minutos de propagación de la config de Google.

---

## Pasos

### 1. Google Cloud Console — crear el OAuth client
- **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
- Tipo de aplicación: **Web application**.
- **Authorized JavaScript origins:**
  - `https://armador-apus.onrender.com`
  - `http://localhost:5173`
- **Authorized redirect URIs:**
  - `https://<project-ref>.supabase.co/auth/v1/callback`
  - (`<project-ref>` es el subdominio del proyecto Supabase: Settings → API en el
    dashboard de Supabase, o la env `SUPABASE_URL`/`SUPABASE_PROJECT_REF` en Render.)
- **Pantalla de consentimiento (OAuth consent screen):** si el Workspace de Google es
  el de la empresa, elegir **Internal**. Así Google mismo filtra a `@indugravas.com`
  antes de que la petición llegue al RBAC de la app — una capa extra, gratis. Si no
  hay Workspace (o el proyecto de Google no pertenece a uno), la opción Internal ni
  aparece y toca usar External; en ese caso el único filtro de "quién entra" es la
  invitación del Admin, no Google.
- Al terminar, Google muestra el **Client ID** y el **Client Secret**: cópialos, se
  usan en el paso 2.

### 2. Supabase — habilitar el provider de Google
- **Authentication → Providers** → buscar **Google** en la lista → habilitar (toggle
  ON) → pegar **Client ID** y **Client Secret** del paso 1 → guardar.

### 3. Supabase — Redirect URLs
- **Authentication → URL Configuration → Redirect URLs** → agregar (si no están ya de
  la config de correo, ver `docs/runbook-correo-resend-smtp.md`):
  - `https://armador-apus.onrender.com/**`
  - `http://localhost:5173/**`

---

## Ajustes de Supabase que tienen que quedar así (y por qué)

Esto no es parte de configurar Google en sí: son cuatro ajustes generales de
Authentication que la guarda de adopción de perfiles da por sentado. Revisarlos ahora,
antes de aprobar el merge — si están mal, la feature abre una puerta que no debería.

### Confirm email: ON
- **Dónde:** Authentication → Providers → **Email** (desplegar) → toggle **Confirm
  email**. *(Nombre y pantalla exactos: verificar en el dashboard — Supabase reordena
  estas pantallas de tanto en tanto y no pude confirmarlo con una fuente 100% actual.)*
- **Por qué importa:** si está apagado, registrarse con cualquier correo alcanza para
  "tenerlo" sin controlar la bandeja de entrada. La adopción por email
  (`_adoptar_por_email` en `auth.py`) asume que un perfil con ese email + una sesión
  respaldada por Google son la misma persona. Si además cualquiera puede quedarse un
  correo con solo registrarse (sin confirmarlo), alguien podría intentar reclamar el
  perfil de un invitado real sin ser su dueño.
- Ya estaba señalado como pendiente de verificar en la auditoría de julio
  (`docs/auditoria-codigo-2026-07-08.md:197-198`): *"el bootstrap admin confía en el
  claim `email`; la seguridad depende de que Supabase esté en invite-only / email
  confirmado."* Este runbook cierra ese pendiente.

### Manual linking (identidades): OFF
- **Dónde:** *verificar el nombre y la pantalla exactos en el dashboard.* La
  documentación oficial de Supabase lo describe solo como "las opciones de
  configuración de autenticación de tu proyecto", sin fijar una ruta estable de
  pantalla; no lo pude confirmar con precisión. Es un toggle de tipo
  "Enable/Allow manual linking", **apagado por default** — este paso es para
  **confirmar que sigue apagado**, no para tocarlo.
- **Por qué importa:** con manual linking encendido, un usuario ya autenticado puede
  vincular una identidad de Google a su propia cuenta aunque el email de esa identidad
  de Google no sea el suyo (`auth.linkIdentity()` client-side). Eso rompe la premisa
  de la guarda: "sesión respaldada por un proveedor externo" deja de implicar "el
  email de la sesión es el que Google verificó". Un atacante podría vincular Google a
  una cuenta cuyo email no controla.

### Secure email change: ON
- **Dónde:** *verificar el nombre y la pantalla exactos en el dashboard* (Authentication
  → Providers → **Email**, junto a *Confirm email*; Supabase reordena estas pantallas de
  tanto en tanto). El toggle exige confirmación (desde el correo VIEJO, o desde ambos
  según la versión) antes de aplicar un cambio de `auth.users.email`.
- **Por qué importa:** con esta rama, la autorización se ancla en el correo de la
  sesión — es lo que busca `perfiles.get_por_email` en la adopción. Y `auth.users.email`
  lo cambia el propio usuario desde el navegador con
  `supabase.auth.updateUser({ email })` y la anon key, sin pasar por el backend. Sin
  confirmación del cambio, cualquiera con su propia cuenta de Google se cambia el correo
  al de la víctima y se adopta su perfil (y su rol) en el siguiente login: la guarda de
  "proveedor externo confiable" (arreglo 1 de esta rama) no ayuda acá, porque el atacante
  SÍ tiene una sesión de Google genuina — el problema es de qué correo dice tener, no de
  qué proveedor lo respalda.
- **Contexto honesto:** esta no es una suposición nueva de esta rama. El bootstrap por
  `APU_ADMIN_EMAILS` (`resolver_perfil`, ver abajo) ya confiaba en el claim `email` desde
  antes de que existiera el login con Google — la auditoría de julio ya lo señalaba
  (`docs/auditoria-codigo-2026-07-08.md:197-198`). Lo que esta rama hace es **ensanchar
  el radio** de esa misma suposición: de los correos listados en `APU_ADMIN_EMAILS` (un
  puñado) a toda la tabla `perfiles` (cualquier invitado). Por eso este ajuste, que antes
  era "deseable", ahora es un requisito de la feature.

### Allow new users to sign up: revisar la tensión con la política de invitación
- **Dónde:** *verificar el nombre y la pantalla exactos en el dashboard*
  (Authentication → Providers → **Email**, o la sección general de Auth — el nombre
  documentado por Supabase es *"Allow new users to sign up"*).
- **Por qué importa, y por qué NO hay un valor correcto único:** un `user_id` **nuevo**
  que llega por Google —el caso típico que dispara la adopción, cuando al invitado nunca
  le pusieron contraseña— **es un signup** a ojos de Supabase, aunque la persona ya
  tuviera un perfil en `perfiles`. Este proyecto declara los signups **cerrados** como
  diseño (`docs/superpowers/specs/2026-07-01-produccion-multiusuario-design.md:115-118`:
  *"Registro público desactivado"* / *"Invitación-solo (sin signup público)"*), y esa
  decisión es correcta — dejarlos abiertos permitiría que cualquier `@gmail.com` se
  registrara solo. Pero con los signups cerrados, el login de Google de alguien cuya
  identidad Supabase no vinculó automáticamente **va a fallar antes de llegar a este
  backend**: GoTrue rechaza el signup implícito con algo como *«Signups not allowed for
  this instance»*, y la adopción por email de este runbook nunca alcanza a correr.
- **La tensión, dicha directamente:** con signups cerrados (el valor que este proyecto
  quiere), la adopción por email queda restringida a un caso residual: cuando el usuario
  de Auth **ya existe** pero con un `user_id` distinto al que quedó guardado en
  `perfiles` — por ejemplo los usuarios que se borraron y recrearon en la limpieza de
  duplicados de producción. Ojo con el caso que **no** es: si Supabase vincula la
  identidad de Google al mismo `user_id` que ya estaba, la adopción **nunca corre**,
  porque `alm.perfiles.get(user_id)` acierta y el perfil de siempre sigue aplicando
  (`apu_tool/servicio/auth.py:208-210`, y ver "Qué esperar la primera vez" más abajo).
  Y a un `user_id` genuinamente nuevo GoTrue lo bloquea antes de que el código de
  adopción lo vea. El
  remedio para ese caso **no es la adopción**: es la vía manual, el Admin arreglando el
  usuario a mano en el dashboard de Supabase (ver "Si algo falla" más abajo). No hay un
  ajuste de este toggle que resuelva ambos casos a la vez sin abrir signups públicos.

---

## Verificación (cómo saber que quedó bien)

### Qué esperar la primera vez
- Si Supabase vincula la identidad de Google al **mismo** `user_id` que ya tenía el
  invitado (linking automático por email, cuando el usuario ya existía con
  contraseña): no pasa nada especial, el perfil de siempre sigue aplicando.
- Si Supabase crea un `user_id` **nuevo** (el caso típico: al invitado nunca le
  pusieron contraseña, solo lo invitaron): el backend adopta el perfil existente por
  email y lo re-clava a ese `user_id` nuevo. Queda un registro
  `usuario.vincular_identidad` en **Auditoría** (`/auditoria`, solo Admin): que la fila
  exista o no es lo que te dice cuál de los dos casos ocurrió. (La **señal** que la
  permitió va en el `contexto` de esa fila, que la página no muestra; ver más abajo.)

### Antes de aprobar el merge: leer el token con tus propios ojos

Este paso **no es opcional**. La guarda `identidad_verificada()` en
`apu_tool/servicio/auth.py` es *fail-closed*: si el token real de Google-vía-Supabase no
trae `app_metadata.provider(s)` con `"google"` — la señal que exige siempre — la
adopción simplemente no corre, sin importar nada más, y un invitado legítimo se queda
con un 403 sin ningún error visible que apunte a la causa real. Confirmar con los ojos
que la señal está presente, una vez, es la única forma de saber que el fail-closed no
se disparó por defecto.

Cómo hacerlo, después del primer login real con Google:
1. Login con Google en `https://armador-apus.onrender.com` (o en local).
2. Abrir devtools del navegador → **Application** (Chrome) o **Storage** (Firefox) →
   **Local Storage** → buscar la clave `sb-<project-ref>-auth-token` (así nombra sus
   claves supabase-js; `<project-ref>` es el mismo subdominio de siempre).
   `(await window.supabase?.auth.getSession())` **no** funciona desde la consola: el
   cliente de supabase-js no queda expuesto como variable global en esta app.
3. El valor es JSON; adentro está el campo `access_token`. Copiarlo.
4. Pegarlo en **jwt.io** (o decodificar a mano: un JWT es
   `base64url(header).base64url(payload).firma`) y mirar el payload.
5. Buscar en el payload:
   - `app_metadata.provider` o `app_metadata.providers`: que incluya `"google"`. Es
     condición NECESARIA — sin esto, la guarda deniega sin importar `amr`.
   - `amr`: si el token trae esta lista, alguno de sus métodos tiene que ser
     `"oauth"` (p.ej. `{"method": "oauth", ...}`). Si `amr` no aparece en el token
     (o es una lista vacía), no hace falta: la señal de cuenta de arriba alcanza sola.

Qué significa el resultado:
- **`app_metadata` no trae `"google"`:** **no** aprobar. La guarda va a denegar a
  todos los invitados por Google sin importar lo demás — revisar de nuevo el
  provider de Google en Supabase.
- **`app_metadata` trae `"google"` y no hay `amr` en el token:** la guarda va a
  funcionar (se queda con la señal de cuenta). Aprobar el merge.
- **`app_metadata` trae `"google"` y `amr` también aparece:** revisar sus métodos.
  Si alguno es `"oauth"`, la guarda funciona; si son todos `"password"` (u otro
  método que no sea `oauth`), la guarda va a denegar **esta sesión en particular**,
  aunque la cuenta tenga Google vinculado — repetir el login asegurándose de haber
  entrado con el botón de Google, no con el formulario de contraseña.

**El atajo de React DevTools NO sirve como prueba, ni siquiera para `provider`/
`providers`.** `session.user.app_metadata` (lo que se ve inspeccionando el nodo
`AuthProvider` en el árbol de componentes) es la señal de CUENTA — la misma que el
paso 5 pide ver en el JWT — pero React DevTools no tiene forma de mostrar `amr`, que
solo vive en el JWT. Antes de este runbook, ver `"google"` en `app_metadata` alcanzaba
para saber que la guarda iba a pasar; ya no: con el arreglo que exige "sesión, no solo
cuenta" (`identidad_verificada()` en `apu_tool/servicio/auth.py`), una cuenta con Google
vinculado que en este login entró por contraseña **también** muestra `"google"` en
`session.user.app_metadata` y sin embargo la guarda deniega esa sesión — porque su
`amr` dice `password`, algo que devtools no puede mostrar. Ver `"google"` ahí ya no
prueba que la guarda vaya a pasar: sigue haciendo falta decodificar el `access_token`
(pasos 1-5) para ver `amr`. No hay atajo.

Una vez desplegado hay una forma de confirmar la señal después, sin repetir este paso a
mano: cada adopción por email deja una fila `usuario.vincular_identidad` cuyo `contexto`
guarda la señal exacta que la disparó (`amr:oauth` o `app_metadata:google`).

**Ojo con dónde mirarla:** la página **Auditoría** (`/auditoria`, solo Admin) muestra la
fila pero **no** renderiza el `contexto` para esta acción (`web/src/pages/Auditoria.tsx`
solo pinta `antes → despues`). Para ver la señal hay que mirar el JSON de
`GET /api/auditoria`, donde el campo sí viaja. O sea: la página te dice **que** hubo una
adopción; el JSON te dice **por qué señal** se permitió.

Sirve para confirmar que la guarda está viva después del hecho, pero no reemplaza este
paso ANTES del merge: sin la verificación de
los pasos 1-5, un fail-closed que deniega a todos los invitados por Google no deja
ninguna fila en auditoría que lo delate (no hay adopción que registrar si nadie logra
entrar).

---

## Si algo falla

### Un invitado ve "no autorizado" (403)
1. Ir a **Usuarios** en el menú (solo Admin) o `GET /api/usuarios` → buscar su correo.
2. **¿Hay dos perfiles con ese correo?** La adopción no adivina a propósito
   (`perfiles.email` no es UNIQUE, y en producción ya hubo perfiles duplicados). Con
   más de uno, la adopción no re-clava ningún perfil y el invitado cae en el mismo 403
   de "no autorizado". Desactivar o corregir el que sobra y pedirle que reintente.
3. **¿El perfil de ese correo está `inactivo`?** Es deliberado, no un bug: un perfil
   inactivo no se adopta aunque sea el único con ese correo — no tiene sentido
   reclavar una fila que de todos modos terminaría denegando. Reactivarlo desde
   **Usuarios** → botón **Activar** en su fila.
- **No llega a la pantalla de Google / redirige a un error:** revisar que el
  Redirect URI en Google (paso 1) y el Client ID/Secret en Supabase (paso 2) coincidan
  exactamente, y que las Redirect URLs (paso 3) incluyan el origen desde el que se
  está probando (`localhost:5173` en local, el dominio de Render en producción).

### El invitado ve un error de Google/Supabase que dice algo como "Signups not allowed"
Es la tensión de **Allow new users to sign up** (ver arriba), no un bug del código de
esta rama: pasa cuando Supabase le da al invitado un `user_id` genuinamente nuevo (nunca
había puesto contraseña) y los signups están cerrados, como este proyecto los quiere.
GoTrue rechaza el intento **antes** de que la adopción por email tenga oportunidad de
correr — no hay nada que este backend pueda hacer, porque la petición nunca llega a
`/api`.

`web/src/pages/Login.tsx` ahora lee el `error`/`error_description` que Supabase agrega
al redirect de vuelta y lo muestra con un toast — pero ojo, esto solo alcanza a
mostrarse si el navegador vuelve a aterrizar en `/login` con el error todavía en la URL.
El botón de Google apunta a `/corridas` (`Login.tsx`, `redirectTo`), no a `/login`: si el
error sí vuelve a la app vía ese redirect, primero pasa por `/corridas` y el guard
`RutaProtegida` (`web/src/components/rutas.tsx`) redirige sin sesión a `/login` con un
`<Navigate>` de React Router, que **no** conserva el hash/query de la URL anterior. En
ese caso el toast puede no llegar a mostrarse igual, y el diagnóstico confiable sigue
siendo este mismo paso: buscar al usuario por correo en el dashboard de Supabase
(Authentication → Users) o, si la petición SÍ llegó al backend pero no hubo adopción,
la ausencia de una fila nueva en **Auditoría**.

El remedio es manual, no la adopción: un Admin entra al dashboard de Supabase
(Authentication → Users), busca al usuario por correo y o bien (a) invita de nuevo desde
la app para que el flujo de siempre le cree contraseña, o bien (b) revisa por qué
Supabase no vinculó la identidad de Google al `user_id` que ya tenía (linking automático
por email fallido) y lo corrige a mano.

---

## Trampas que hay que conocer (para más adelante)

Dos comportamientos no obvios que trae esta feature. No son bugs — son intencionales —
pero si no se conocen, muerden.

**Desactivar el perfil de alguien listado en `APU_ADMIN_EMAILS` NO lo revoca.** El
bootstrap de `resolver_perfil` (`apu_tool/servicio/auth.py:189-224`) es incondicional:
dispara cada vez que no hay perfil resuelto **para el `user_id` de esa sesión**, sin
mirar por qué está vacío. Con un `user_id` nuevo (justo lo que puede traer un login
con Google) y un perfil viejo con ese email en estado `inactivo`, la adopción por
email no lo re-clava (perfil inactivo, ver arriba) — pero eso deja `p` en `None`, y el
bootstrap entra igual: si el email sigue en `APU_ADMIN_EMAILS`, crea un perfil admin
**nuevo y activo** bajo ese `user_id` nuevo, sin excepción, dejando el perfil viejo
inactivo como fila huérfana. Verificado ejecutando `resolver_perfil` contra un
`Almacen` de prueba: perfil admin inactivo + su email en `APU_ADMIN_EMAILS` + `user_id`
nuevo → vuelve un `Perfil(rol="admin", estado="activo")` para ese `user_id` nuevo.

En corto: **desactivar el perfil no alcanza para sacarle el acceso a alguien de
`APU_ADMIN_EMAILS`** — si esa persona conserva acceso a su cuenta de Google, se
auto-reinstala como admin en el siguiente login. Para revocar de verdad hacen falta
**las dos cosas**: sacar el email de `APU_ADMIN_EMAILS` en las variables de entorno de
Render, **y** dejar (o poner) su perfil en `inactivo`. Con el email todavía en la lista
pero el perfil inactivo, el bootstrap lo re-admite igual (es exactamente el caso de
arriba); con el perfil todavía activo pero el email ya fuera de la lista, la adopción
por email lo re-clava igual porque el perfil sigue activo. Ambas cosas verificadas por
ejecución.

El corolario tranquilizador es el mismo hecho visto al revés: el dueño de la app
**no** puede quedar afuera de su propia app por desactivar su perfil por error —
mientras su email siga en `APU_ADMIN_EMAILS`, el bootstrap se lo vuelve a dar en el
siguiente login. `APU_ADMIN_EMAILS` (env de Render) sigue siendo el break-glass real;
no hace falta tocar `seguridad.perfiles` a mano para recuperarlo.

**Ese corolario tiene un límite: solo funciona si el perfil viejo quedó `inactivo` o no
existe.** Si en cambio quedó **activo pero degradado** (alguien le bajó el rol a
`editor`/`consulta` por error, sin desactivarlo), el bootstrap NUNCA corre: `p` no es
`None` —ni por `get(user_id)` directo, ni por la adopción, que solo se salta perfiles
`inactivo`— así que `resolver_perfil` devuelve ese perfil degradado tal cual (línea
`if p is not None: ... return p`, antes de siquiera mirar `APU_ADMIN_EMAILS`). El dueño
entra, pero como `editor`/`consulta`, con su correo todavía en la lista. El break-glass
real para ESE caso es manual: **Usuarios** → subirle el rol a `admin` a mano (no hay
comando de CLI para esto — `run_cli.py` no tiene subcomando de perfiles/usuarios — así
que sin acceso a la UI el remedio es un `UPDATE` directo en `seguridad.perfiles`).

**Si se borra un usuario en Supabase Auth, desactivar su perfil en la app.** La app no
tiene forma de borrar un perfil (solo desactivarlo), pero en Supabase Auth sí se han
borrado usuarios en producción (la limpieza de duplicados, ver
`docs/runbook-correo-resend-smtp.md` → "Después de que funcione"). Un perfil `activo`
sin usuario detrás sigue siendo reclamable: cualquiera que logre autenticarse con ese
correo (por ejemplo registrándose de nuevo, si "Confirm email" estuviera mal puesto) se
lo puede quedar. Regla fija: **borrar usuario en Supabase ⇒ desactivar su perfil en
Usuarios en el mismo momento.**

---

## Valores rápidos (copiar/pegar)

```
Authorized JavaScript origins (Google):
  https://armador-apus.onrender.com
  http://localhost:5173

Authorized redirect URI (Google):
  https://<project-ref>.supabase.co/auth/v1/callback

Redirect URLs (Supabase → Authentication → URL Configuration):
  https://armador-apus.onrender.com/**
  http://localhost:5173/**
```

`<project-ref>` es el subdominio del proyecto Supabase (Settings → API en el
dashboard, o las envs `SUPABASE_URL` / `SUPABASE_PROJECT_REF` en Render).
