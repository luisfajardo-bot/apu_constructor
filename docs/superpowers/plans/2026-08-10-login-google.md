# Ingresar con la cuenta de Google — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un usuario invitado pueda entrar con su cuenta de Google, sin definir contraseña, y que el RBAC siga siendo el mismo (sin invitación, no entra).

**Architecture:** La autenticación sale gratis: `servicio/auth.py` ya verifica el JWT de Supabase contra su JWKS, y ese token es el mismo venga de contraseña o de Google. Lo único que hay que resolver es la puerta: `resolver_perfil` busca el perfil por `user_id`, así que si Supabase no vincula la identidad de Google al usuario que creó la invitación, el invitado llega con un `user_id` nuevo y sin perfil. Se agrega una **adopción por email** con tres guardas (email verificado, exactamente un perfil con ese email, y se re-clava el perfil en vez de duplicarlo). En el frontend es un botón.

**Tech Stack:** Python 3 + FastAPI + PyJWT + SQLite/psycopg (dos backends espejo), pytest; React 19 + TypeScript + supabase-js + vitest. Supabase Auth y Google Cloud Console para lo manual.

**Spec:** `docs/superpowers/specs/2026-08-10-login-google-design.md`

## Global Constraints

- **Rama:** `feat/login-google`, creada desde `master`. No se hace push a `master` sin aprobación explícita del usuario (auto-despliega).
- **La invitación sigue siendo obligatoria.** Nada de auto-autorizar el dominio `@indugravas.com`. Un usuario sin perfil recibe 403 igual que hoy.
- **El login por contraseña se queda.** Es un botón más, no un reemplazo.
- **Español** en comentarios y mensajes de usuario.
- **Sin dependencias nuevas** (ni backend ni frontend).
- **Los dos backends van juntos:** todo método nuevo va al `Protocol` de `apu_tool/datos/repositorio.py` + SQLite + Postgres.
- **La CSP no se toca.** La navegación a `accounts.google.com` no la gobierna la CSP y el canje del `?code=` va al host de Supabase, ya presente en `connect-src`.
- `resolver_perfil` no debe saber de JWTs: el parámetro nuevo es un `bool`, no los claims. Es lo que la hace testeable sin red.
- Verificación: `python -m pytest tests/ -q`; frontend `cd web && npm run build` (es `tsc -b`) y `npx vitest run`.

---

### Task 1: `get_por_email` y `reasignar_user_id` en el contrato y los dos backends

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (`class RepositorioPerfiles`, líneas 198-210)
- Modify: `apu_tool/datos/perfiles_db.py` (después de `listar`, línea 62-65)
- Modify: `apu_tool/datos/pg/perfiles_pg.py` (después de `listar`, línea 47-50)
- Test: `tests/test_perfiles_contrato.py` (corre contra SQLite siempre y contra Postgres si hay `TEST_DATABASE_URL`)

**Interfaces:**
- Consumes: nada.
- Produces:
  - `RepositorioPerfiles.get_por_email(email: str) -> list[Perfil]`
  - `RepositorioPerfiles.reasignar_user_id(viejo: str, nuevo: str, conn=None) -> None`

- [ ] **Step 1: Crear la rama**

```bash
git checkout master
git checkout -b feat/login-google
```

- [ ] **Step 2: Escribir los tests que fallan**

Al final de `tests/test_perfiles_contrato.py`:

```python
def test_get_por_email_devuelve_lista(repo):
    """Lista y no Optional a propósito: `perfiles.email` NO es UNIQUE, y esconder el
    caso ambiguo es justo lo que no queremos (ver el spec)."""
    repo.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    assert [p.user_id for p in repo.get_por_email("ana@obra.co")] == ["u1"]
    assert repo.get_por_email("nadie@obra.co") == []


def test_get_por_email_ignora_caso_y_espacios(repo):
    repo.upsert(Perfil("u1", "Ana@Obra.CO", "editor", "activo"))
    assert len(repo.get_por_email("  ana@obra.co ")) == 1


def test_get_por_email_puede_devolver_varios(repo):
    repo.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    repo.upsert(Perfil("u2", "ana@obra.co", "consulta", "activo"))
    assert len(repo.get_por_email("ana@obra.co")) == 2


def test_reasignar_user_id_mueve_el_perfil(repo):
    repo.upsert(Perfil("viejo", "ana@obra.co", "editor", "activo", "Ana"))
    repo.reasignar_user_id("viejo", "nuevo")
    assert repo.get("viejo") is None
    p = repo.get("nuevo")
    assert p.email == "ana@obra.co" and p.rol == "editor" and p.nombre == "Ana"
    assert len(repo.listar()) == 1        # se movió, no se duplicó
```

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_perfiles_contrato.py -q`
Expected: FAIL con `AttributeError: 'PerfilesDB' object has no attribute 'get_por_email'`

- [ ] **Step 4: Agregar al Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioPerfiles`, después de
`upsert`:

```python
    def get_por_email(self, email: str) -> list[Perfil]:
        """Perfiles con ese email (comparado en minúsculas y sin espacios).

        Devuelve una LISTA porque `perfiles.email` no es UNIQUE: puede haber 0, 1 o
        varios. Quien decide qué hacer con el caso ambiguo es `servicio/auth.py`, no
        el repositorio."""
        ...

    def reasignar_user_id(self, viejo: str, nuevo: str, conn=None) -> None:
        """Mueve un perfil a otro `user_id` (misma fila, nueva PK).

        Es lo que hace la adopción por email cuando Supabase entrega un `user_id`
        nuevo para un usuario ya invitado. Se mueve y no se duplica: dos filas del
        mismo email descuadrarían el guard del último Admin activo, que cuenta filas."""
        ...
```

- [ ] **Step 5: Implementar en SQLite**

En `apu_tool/datos/perfiles_db.py`, después de `listar`:

```python
    def get_por_email(self, email: str) -> list[Perfil]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM perfiles WHERE lower(trim(email)) = ? ORDER BY user_id",
                ((email or "").strip().lower(),)).fetchall()
        return [self._fila(r) for r in rows]

    def reasignar_user_id(self, viejo: str, nuevo: str, conn=None) -> None:
        sql = "UPDATE perfiles SET user_id=? WHERE user_id=?"
        if conn is not None:
            conn.execute(sql, (nuevo, viejo)); return
        with self.connect() as c:
            c.execute(sql, (nuevo, viejo))
```

- [ ] **Step 6: Implementar en Postgres**

En `apu_tool/datos/pg/perfiles_pg.py`, después de `listar`:

```python
    def get_por_email(self, email: str) -> list[Perfil]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM seguridad.perfiles WHERE lower(trim(email)) = %s "
                "ORDER BY user_id",
                ((email or "").strip().lower(),)).fetchall()
        return [self._fila(r) for r in rows]

    def reasignar_user_id(self, viejo: str, nuevo: str, conn=None) -> None:
        sql = "UPDATE seguridad.perfiles SET user_id=%s WHERE user_id=%s"
        if conn is not None:
            conn.execute(sql, (nuevo, viejo)); return
        with self.cx.connection() as c:
            c.execute(sql, (nuevo, viejo))
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_perfiles_contrato.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/perfiles_db.py apu_tool/datos/pg/perfiles_pg.py tests/test_perfiles_contrato.py
git commit -m "feat(datos): get_por_email y reasignar_user_id en el repo de perfiles"
```

---

### Task 2: adopción por email en `resolver_perfil`

**Files:**
- Modify: `apu_tool/servicio/auth.py` (`resolver_perfil` líneas 72-91; `usuario_actual` líneas 101-113)
- Test: `tests/test_auth_google.py` (nuevo)

**Interfaces:**
- Consumes: `alm.perfiles.get_por_email(email)` y `alm.perfiles.reasignar_user_id(viejo, nuevo, conn=...)` de Task 1.
- Produces: `resolver_perfil(alm, user_id: str, email: str, email_verificado: bool = False) -> Perfil`. El default `False` mantiene compatibles las llamadas de 3 argumentos que ya existen en `tests/test_auth_rbac.py`, y significa "sin prueba de que el email sea suyo, no se adopta nada".

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_auth_google.py`:

```python
"""Adopción por email: el invitado entra con Google aunque Supabase le dé otro user_id.

Spec: docs/superpowers/specs/2026-08-10-login-google-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import ErrorAuth, resolver_perfil


def _alm(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_perfil_por_user_id_no_pasa_por_la_adopcion(tmp_path, monkeypatch):
    """El camino de siempre no cambia: si el user_id ya tiene perfil, no se toca nada."""
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    assert resolver_perfil(alm, "u1", "ana@obra.co", True).rol == "editor"
    _items, total = alm.auditoria.listar(accion="usuario.vincular_identidad")
    assert total == 0


def test_adopta_cuando_el_email_esta_verificado(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "editor", "activo", "Ana"))
    p = resolver_perfil(alm, "nuevo-de-google", "ana@obra.co", True)
    assert p.user_id == "nuevo-de-google" and p.rol == "editor" and p.nombre == "Ana"
    assert alm.perfiles.get("viejo") is None
    assert alm.perfiles.get("nuevo-de-google").rol == "editor"
    items, total = alm.auditoria.listar(accion="usuario.vincular_identidad")
    assert total == 1 and items[0]["entidad_id"] == "nuevo-de-google"


def test_email_sin_verificar_no_adopta_nada(tmp_path, monkeypatch):
    """El test de la escalada de privilegios: sin esta guarda, cualquiera que se registre
    con el correo del Admin y no lo confirme se queda con su perfil."""
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("el-jefe", "jefe@obra.co", "admin", "activo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "impostor", "jefe@obra.co", False)
    assert alm.perfiles.get("el-jefe").rol == "admin"      # intacto
    assert alm.perfiles.get("impostor") is None


def test_dos_perfiles_con_el_mismo_email_no_se_adivina(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    alm.perfiles.upsert(Perfil("u2", "ana@obra.co", "admin", "activo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "nuevo", "ana@obra.co", True)
    assert alm.perfiles.get("u1") is not None and alm.perfiles.get("u2") is not None


def test_perfil_adoptado_inactivo_no_se_cuela(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "editor", "inactivo"))
    with pytest.raises(ErrorAuth, match="inactivo"):
        resolver_perfil(alm, "nuevo", "ana@obra.co", True)


def test_email_con_otro_caso_y_espacios_igual_adopta(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "consulta", "activo"))
    assert resolver_perfil(alm, "nuevo", " Ana@Obra.CO ", True).rol == "consulta"


def test_bootstrap_admin_sigue_funcionando_sin_perfil_previo(tmp_path, monkeypatch):
    """La adopción va ANTES del bootstrap, pero sin perfil que adoptar no lo estorba."""
    alm = _alm(tmp_path, monkeypatch)
    monkeypatch.setenv("APU_ADMIN_EMAILS", "jefe@obra.co")
    assert resolver_perfil(alm, "u-jefe", "jefe@obra.co", True).rol == "admin"


def test_sin_perfil_y_sin_ser_admin_sigue_denegando(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "ajeno", "ajeno@gmail.com", True)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_auth_google.py -v`
Expected: FAIL. `resolver_perfil` acepta 3 argumentos (`TypeError`) y no adopta nada.

- [ ] **Step 3: Escribir la adopción**

En `apu_tool/servicio/auth.py`, agregar `from dataclasses import replace` a los imports y
reemplazar `resolver_perfil`:

```python
def _adoptar_por_email(alm: Almacen, user_id: str, email: str) -> Optional[Perfil]:
    """Re-clava a `user_id` el perfil de ese email, si hay EXACTAMENTE uno. None si no.

    Es lo que permite que un invitado entre con Google cuando Supabase le entrega un
    `user_id` distinto al que creó la invitación. El llamador ya verificó que el email
    viene verificado por el proveedor: sin eso, alguien que se registre con el correo de
    otro y no lo confirme se quedaría con su perfil (y con su rol).

    Con dos perfiles del mismo email no se adivina: devuelve None y el llamador deniega.
    `perfiles.email` no es UNIQUE y en producción ya hubo usuarios duplicados."""
    candidatos = alm.perfiles.get_por_email(email)
    if len(candidatos) != 1:
        return None
    viejo = candidatos[0]
    with alm.transaccion("seguridad") as conn:
        alm.perfiles.reasignar_user_id(viejo.user_id, user_id, conn=conn)
        registrar_auditoria(alm, conn, None, "usuario.vincular_identidad", "usuario",
                            user_id, antes={"user_id": viejo.user_id, "email": viejo.email},
                            despues={"user_id": user_id, "email": viejo.email,
                                     "rol": viejo.rol})
    return replace(viejo, user_id=user_id)


def resolver_perfil(alm: Almacen, user_id: str, email: str,
                    email_verificado: bool = False) -> Perfil:
    """Devuelve el Perfil activo del usuario; bootstrap admin por APU_ADMIN_EMAILS.

    `email_verificado` es lo que dice el proveedor de identidad (Google siempre manda
    true). Solo con eso en true se intenta la adopción por email. El default es False
    para que la ausencia de prueba nunca adopte nada.

    Lanza ErrorAuth si el usuario está inactivo o no está autorizado (no invitado).
    """
    p = alm.perfiles.get(user_id)
    if p is None and email_verificado:
        p = _adoptar_por_email(alm, user_id, email)
    if p is not None:
        if p.estado != "activo":
            raise ErrorAuth("Usuario inactivo.")
        return p
    if (email or "").strip().lower() in config.admin_emails():
        nuevo = Perfil(user_id=user_id, email=email, rol="admin", estado="activo",
                       nombre="", creado_en=_dt.date.today().isoformat())
        with alm.transaccion("seguridad") as conn:
            alm.perfiles.upsert(nuevo, conn=conn)
            registrar_auditoria(alm, conn, None, "usuario.bootstrap_admin", "usuario", user_id,
                                antes=None,
                                despues={"email": email, "rol": "admin", "estado": "activo"})
        return nuevo
    raise ErrorAuth("Usuario no autorizado (no invitado).")
```

Agregar `Optional` al import de typing del archivo si no está.

- [ ] **Step 4: Pasar el claim desde `usuario_actual`**

En `apu_tool/servicio/auth.py::usuario_actual`:

```python
    user_id = claims.get("sub", "")
    email = claims.get("email", "")
    # Lo pone el proveedor de identidad: Google manda true; un signup por contraseña sin
    # confirmar, no. Es la única prueba de que el email es suyo, y de eso depende la
    # adopción por email de resolver_perfil.
    verificado = bool((claims.get("user_metadata") or {}).get("email_verified"))
    try:
        return resolver_perfil(alm, user_id, email, verificado)
    except ErrorAuth as e:
        raise HTTPException(status_code=403, detail=str(e))
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_auth_google.py -v`
Expected: PASS los 8.

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. `tests/test_auth_rbac.py` llama `resolver_perfil` con 3 argumentos y sigue
funcionando por el default `False`.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/auth.py tests/test_auth_google.py
git commit -m "feat(auth): adopcion por email para que el invitado entre con Google"
```

---

### Task 3: el botón en la pantalla de ingreso

**Files:**
- Modify: `web/src/pages/Login.tsx` (después del `</form>`, línea 117)
- Test: `web/src/pages/Login.test.tsx`

**Interfaces:**
- Consumes: `supabase.auth.signInWithOAuth` de `@/lib/supabase` (el cliente ya está importado en la página para `resetPasswordForEmail`).
- Produces: nada que consuma otra tarea.

- [ ] **Step 1: Escribir el test que falla**

En `web/src/pages/Login.test.tsx`, agregar `signInWithOAuth` al mock del cliente y el test:

```tsx
const signInWithOAuth = vi.fn(async () => ({ error: null }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { resetPasswordForEmail: vi.fn(), signInWithOAuth } },
}));

test("el botón de Google pide el OAuth con el redirect al origen actual", async () => {
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: /google/i }));
  await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledWith({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/corridas` },
  }));
});
```

**Ojo:** el mock de `@/lib/supabase` ya existe en el archivo (línea 7). Hay que
**modificarlo**, no agregar un segundo `vi.mock` del mismo módulo. Y `signInWithOAuth`
tiene que declararse antes del `vi.mock` (como ya se hace con `login`), porque `vi.mock`
se iza al principio del archivo.

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `cd web && npx vitest run src/pages/Login.test.tsx`
Expected: FAIL — no hay ningún botón que diga "Google".

- [ ] **Step 3: Agregar el botón**

En `web/src/pages/Login.tsx`, después del `</form>` y antes del párrafo final:

```tsx
      <div className="flex items-center gap-2.5">
        <span className="h-px flex-1 bg-border" />
        <span className="text-[11px] text-muted-foreground">o</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      <Button type="button" variant="outline" size="lg" className="w-full"
              onClick={conGoogle} disabled={enviando}>
        <IconoGoogle />
        Continuar con Google
      </Button>
```

la función, junto a `olvide`:

```tsx
  async function conGoogle() {
    // El backend no cambia: el JWT de Supabase es el mismo venga de contraseña o de
    // Google, y el acceso lo sigue habilitando la invitación de un Admin.
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/corridas` },
    });
    if (error) toast.error(error.message);
  }
```

y el icono al final del archivo (SVG inline: `lucide-react` no trae el logo de Google y la
CSP tiene `img-src 'self' data:`, así que un `<img>` remoto quedaría bloqueado):

```tsx
function IconoGoogle() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-4">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.27-4.74 3.27-8.09Z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z" />
      <path fill="#FBBC05" d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84Z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38Z" />
    </svg>
  );
}
```

- [ ] **Step 4: Correr los tests del frontend**

Run: `cd web && npx vitest run`
Expected: PASS, incluidos `Login.test.tsx` y `Login.a11y.test.tsx` (el botón tiene nombre
accesible por su texto; el separador son `<span>`, no entra al orden de foco).

- [ ] **Step 5: Compilar de verdad**

Run: `cd web && npm run build`
Expected: sin errores. **`npm run build` es `tsc -b`; `tsc --noEmit` no alcanza.**

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Login.tsx web/src/pages/Login.test.tsx
git commit -m "feat(web): boton Continuar con Google en la pantalla de ingreso"
```

---

### Task 4: el runbook de los pasos manuales

Sin esto la feature no funciona en producción y nadie sabe por qué.

**Files:**
- Create: `docs/runbook-login-google.md`

**Interfaces:** ninguna.

- [ ] **Step 1: Escribir el runbook**

Con el mismo formato que `docs/runbook-correo-resend-smtp.md` (leerlo primero para copiar
la estructura), cubriendo:

1. **Google Cloud Console** → APIs & Services → Credentials → Create OAuth client ID,
   tipo *Web application*:
   - Authorized redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback`
   - Authorized JavaScript origins: `https://armador-apus.onrender.com` y
     `http://localhost:5173`
   - Pantalla de consentimiento **Internal** si el Workspace es el de la empresa: así
     Google filtra a `@indugravas.com` antes de que llegue al RBAC.
2. **Supabase** → Authentication → Providers → Google: pegar Client ID y Client Secret,
   habilitar.
3. **Supabase** → Authentication → URL Configuration → Redirect URLs: agregar
   `https://armador-apus.onrender.com/**` y `http://localhost:5173/**`.
4. **Qué esperar la primera vez:** si Supabase vincula la identidad al usuario invitado, el
   `user_id` es el mismo y no pasa nada especial. Si crea uno nuevo, el backend adopta el
   perfil por email y queda un registro `usuario.vincular_identidad` en la auditoría —
   revisar ahí para saber cuál de los dos ocurrió.
5. **Si un invitado ve "no autorizado":** mirar si hay **dos** perfiles con su correo
   (`GET /api/usuarios`); con dos, la adopción no adivina a propósito. Desactivar o
   corregir el que sobra.

- [ ] **Step 2: Commit**

```bash
git add docs/runbook-login-google.md
git commit -m "docs: runbook de los pasos manuales del login con Google"
```

---

### Task 5: configuración real y verificación en el navegador

Esta tarea **no se puede completar sin el usuario**: necesita acceso a Google Cloud y a
Supabase. Pararse acá y pedírselo.

- [ ] **Step 1: Suite completa**

Run: `python -m pytest tests/ -q && cd web && npx vitest run && npm run build`
Expected: todo verde.

- [ ] **Step 2: Pedirle al usuario que haga los pasos 1-3 del runbook**

Son en la consola de Google y en el dashboard de Supabase. Ofrecer que corra los comandos
él mismo con el prefijo `!` si algo se puede verificar por CLI.

- [ ] **Step 3: Levantar la web en local y probar**

Necesita `SUPABASE_URL` y `APU_ADMIN_EMAILS` en el entorno, o todo `/api` responde 401
(receta en la memoria: "Levantar la web en local"). Probar:

- entrar con una cuenta **invitada** → entra y cae en `/corridas`;
- entrar con una cuenta **no invitada** → 403 y la pantalla de "no autorizado";
- el login por contraseña sigue funcionando;
- revisar la auditoría por `usuario.vincular_identidad` para saber si Supabase vinculó la
  identidad o si hizo falta la adopción.

- [ ] **Step 4: Actualizar la memoria del proyecto y pedir aprobación para el push**

`master` auto-despliega a producción: **preguntar** antes de mergear.

---

## Notas de la auto-revisión

- **Cobertura del spec:** los dos métodos del repo (Task 1), la adopción con sus tres
  guardas y el claim `email_verified` (Task 2), el botón y el SVG inline (Task 3), los
  pasos manuales (Task 4), la verificación en navegador (Task 5). La CSP y `AuthProvider`
  no se tocan, como dice el spec.
- **Consistencia de nombres:** `get_por_email(email) -> list[Perfil]`,
  `reasignar_user_id(viejo, nuevo, conn=None)`, `_adoptar_por_email(alm, user_id, email)`,
  `resolver_perfil(alm, user_id, email, email_verificado=False)`, la acción de auditoría
  `usuario.vincular_identidad`. Los mismos en todas las tareas.
- **Riesgo conocido:** si Supabase sí vincula la identidad, la adopción no corre nunca en
  producción y queda cubierta solo por tests. Está declarado en el spec y es aceptado: es
  exactamente el caso que dejaría a un invitado afuera sin explicación.
- **Dependencia entre planes:** ninguna. Este plan y el de
  `2026-08-10-alta-sin-duplicados.md` no tocan ningún archivo en común, así que las dos
  ramas pueden ir en cualquier orden.
