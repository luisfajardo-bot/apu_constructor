# Runbook — Correo transaccional con Resend + Supabase (SMTP)

**Objetivo:** que las **invitaciones** y el **"olvidé contraseña"** envíen correos de forma
confiable en producción. Fecha: 2026-07.

---

## Por qué importa (contexto)

- La app envía correos en dos momentos: **invitar usuarios** y **restablecer contraseña**.
- Hoy usa el **correo integrado de Supabase**, que es **solo para pruebas**: tiene un tope de
  ~2-4 correos por hora. Con el uso real se satura y los correos **dejan de enviarse**.
- Ya lo confirmamos en los logs de Auth de Supabase: error **`over_email_send_rate_limit`**
  (respuestas **429**). Por eso "olvidé contraseña" y algunas invitaciones no llegaban.
- **Solución de producción:** un proveedor SMTP propio. Usamos **Resend** (plan gratis:
  **100 correos/día, 3.000/mes**; confiable; guía oficial con Supabase).
- **Beneficio:** invitaciones y recuperación funcionan sin el tope de prueba, y los correos
  salen **desde tu dominio** (mejor entregabilidad, menos spam).

---

## Requisitos previos

- Acceso al **panel de DNS** de `indugravas.com` (tú o IT).
- Acceso **admin** al proyecto Supabase "BASE APUS".
- ~15 min de trabajo + espera de verificación DNS (minutos a un par de horas).

---

## Pasos

### 1. Crear cuenta en Resend
- Entra a **resend.com** → **Sign up** (gratis).

### 2. Agregar el dominio (usar SUBDOMINIO para no tocar el correo actual)
- Resend → **Domains** → **Add Domain** → escribe **`send.indugravas.com`**.
- Usar un subdominio (`send.`) evita chocar con el SPF/registros del correo `@indugravas.com`
  que ya funciona.

### 3. Copiar los registros DNS y pasarlos a IT
- Resend te mostrará **3-4 registros** para el subdominio (típicamente):
  - un **MX**
  - un **TXT de SPF** (`v=spf1 include:...`)
  - uno o dos **de DKIM** (TXT/CNAME, tipo `resend._domainkey...`)
  - (opcional) un **DMARC**
- Agrégalos **tal cual** (nombre y valor exactos) en el DNS de `indugravas.com`, **para el
  subdominio `send`**.
- Mensaje para IT: *"Son registros para el subdominio `send.indugravas.com`; no afectan el
  correo `@indugravas.com` actual."*

### 4. Verificar
- Resend → el dominio → **Verify** → espera a que quede **Verified**.

### 5. Crear API key
- Resend → **API Keys** → **Create** (permiso de envío) → copia **`re_...`** (no se vuelve a
  mostrar).

### 6. Configurar SMTP en Supabase
- Supabase → **Authentication → Emails → SMTP Settings** → **Enable Custom SMTP**:
  ```
  Sender email:  no-reply@send.indugravas.com
  Sender name:   Armador de APUs
  Host:          smtp.resend.com
  Port:          465          (si 465 falla, usa 587)
  Username:      resend
  Password:      re_...        (la API key de Resend)
  ```
- El **Sender email** debe ser del **dominio verificado**.

### 7. Subir el límite de correos
- Supabase → **Authentication → Rate Limits** → sube **"Emails per hour"**.

### 8. Probar
- En `/login` → **¿Olvidaste tu contraseña?** con tu correo → debe llegar un correo
  **desde `no-reply@send.indugravas.com`**.
- O reenvía una **invitación** → llega y aterriza en `/definir-clave`.

---

## Verificación (cómo saber que quedó bien)

- El correo llega (revisa **spam** la primera vez).
- Resend → **Emails/Logs** muestra el envío como **delivered**.
- Supabase → logs de **auth**: ya **no** aparece `over_email_send_rate_limit`.

---

## Config de auth que debe estar puesta (relacionada)

Para que la invitación y la recuperación redirijan bien:
- Supabase → Authentication → URL Configuration:
  - **Site URL:** `https://armador-apus.onrender.com` (la **raíz**)
  - **Redirect URLs:** `https://armador-apus.onrender.com/definir-clave` y `https://armador-apus.onrender.com/**`
- Render → Environment: **`APU_PUBLIC_URL = https://armador-apus.onrender.com`**.

---

## Si algo falla

- **No llega el correo:** confirma el dominio **Verified** en Resend; revisa spam; mira
  Resend → Logs.
- **"Invalid from address" / rechazo:** el *Sender email* debe ser del dominio verificado.
- **La recuperación redirige mal:** revisa Site URL (raíz) + `/definir-clave` en Redirect URLs
  + `APU_PUBLIC_URL` en Render.
- **Sigue el rate limit:** confirma que Custom SMTP quedó **enabled** (si sigue en el correo
  integrado, no aplica el nuevo límite).

---

## Después de que funcione

- **Limpiar usuarios duplicados/huérfanos** en Supabase → Authentication → Users (dejar uno
  por correo) y asegurar su fila en `seguridad.perfiles`.

## Valores rápidos (copiar/pegar)

```
Resend SMTP host:  smtp.resend.com
Puerto:            465 (o 587)
Usuario:           resend
Password:          <API key re_...>
Remitente:         no-reply@send.indugravas.com
```
