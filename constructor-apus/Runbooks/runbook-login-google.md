> Espejo automático — no editar aquí. Fuente: `docs/runbook-login-google.md`

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

Esto no es parte de configurar Google en sí: son dos ajustes generales de
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

---

## Verificación (cómo saber que quedó bien)

### Qué esperar la primera vez
- Si Supabase vincula la identidad de Google al **mismo** `user_id` que ya tenía el
  invitado (linking automático por email, cuando el usuario ya existía con
  contraseña): no pasa nada especial, el perfil de siempre sigue aplicando.
- Si Supabase crea un `user_id` **nuevo** (el caso típico: al invitado nunca le
  pusieron contraseña, solo lo invitaron): el backend adopta el perfil existente por
  email y lo re-clava a ese `user_id` nuevo. Queda un registro
  `usuario.vincular_identidad` en **Auditoría** (`/auditoria`, solo Admin) — ahí se ve
  cuál de los dos casos ocurrió.

### Antes de aprobar el merge: leer el token con tus propios ojos

Este paso **no es opcional**. La guarda `identidad_verificada()` en
`apu_tool/servicio/auth.py` es *fail-closed*: si el token real de Google-vía-Supabase
no trae ninguna de las dos señales que espera, la adopción simplemente no corre — y un
invitado legítimo se queda con un 403 sin ningún error visible que apunte a la causa
real. Confirmar con los ojos que la señal está presente, una vez, es la única forma de
saber que el fail-closed no se disparó por defecto.

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
5. Buscar **cualquiera** de las dos señales:
   - `amr`: una lista con un objeto `{"method": "oauth", ...}`.
   - `app_metadata.provider` o `app_metadata.providers`: que incluya `"google"`.

Qué significa el resultado:
- **Si aparece alguna de las dos:** la guarda va a funcionar. Aprobar el merge.
- **Si no aparece ninguna:** **no** aprobar. Algo en la config de Google/Supabase no
  está entregando lo que `identidad_verificada()` espera — revisar de nuevo el
  provider de Google en Supabase — y, tal como está, **todos** los invitados que
  entren por Google van a quedar en 403 aunque el resto de la config esté perfecta.

*(Atajo sin decodificar nada a mano: en devtools → React DevTools, buscar en el árbol
de componentes el nodo **`AuthProvider`** e inspeccionar su Context/estado — ahí vive
la `sesion`, y el objeto de sesión de supabase-js trae `session.user.app_metadata` ya
parseado. Sirve para mirar `provider`/`providers`, pero `amr` solo vive en el JWT, así
que para confirmar `amr` específicamente sí hay que decodificar el token.)*

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

---

## Trampas que hay que conocer (para más adelante)

Dos comportamientos no obvios que trae esta feature. No son bugs — son intencionales —
pero si no se conocen, muerden.

**Desactivar el perfil de alguien listado en `APU_ADMIN_EMAILS` NO lo revoca.** El
bootstrap de `resolver_perfil` (`apu_tool/servicio/auth.py:149-165`) es incondicional:
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
