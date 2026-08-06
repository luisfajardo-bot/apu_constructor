> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-06-barra-navegacion-plegable.md`

# Barra con navegación plegable — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que al angostar la ventana las cuatro lecturas de estado dejen de esconderse y sea la navegación la que se pliegue en un desplegable que dice en qué sección estás.

**Architecture:** Un solo archivo de frontend (`web/src/components/Layout.tsx`) más su test. Se invierte el orden de sacrificio de la barra: se le quita `@max-[980px]:hidden` al grupo de lecturas y se le agrega al `<nav>`, que pasa a ser un panel absoluto controlado por un `<button aria-expanded>` visible solo en angosto. Los links se renderizan una sola vez: el mismo `<nav>` es la fila inline en ancho y el panel en angosto. Cero backend, cero dependencias nuevas.

**Tech Stack:** React 19 + TypeScript / Vite / Tailwind v4 (container queries) / vitest + @testing-library/react / react-router-dom / lucide-react

**Spec:** `docs/superpowers/specs/2026-08-06-barra-navegacion-plegable-design.md`

## Global Constraints

- **Español** en nombres, comentarios y texto visible al usuario.
- **Sin dependencias nuevas.** Todo con lo que `Layout.tsx` ya importa (`react`, `react-router-dom`, `lucide-react`, `cn`, `Button`) más `useLocation` y un ícono de chevron de `lucide-react`, que ya está instalado.
- **Las lecturas de estado no se ocultan ni se pliegan en ningún ancho.** Es el punto de la feature.
- **Un solo render del array `links`.** No puede haber una copia ancha y otra angosta del menú en el DOM: rompería el test que afirma que dentro de `<nav>` hay exactamente 5 links.
- **Cerrado, el `<nav>` se oculta SOLO con el modificador `@max-[…]`**, nunca con un `hidden` pelado. En los tests las container queries no existen, así que un `hidden` sin modificador haría desaparecer el `<nav>` y se caerían los guards existentes.
- **Solo el modificador `@max-[…]`**, que el repo ya usa en `Layout.tsx:98,113,153,180`. No introducir `@min-[…]`, que no tiene precedente en este repo.
- **Escalones de ancho** (container queries sobre la barra, que ya es `@container`): `<1180` se va el correo *(ya existe)* · `<980` se pliega la navegación *(nuevo)* · `<700` se va el nombre de la marca *(ya existe)* · `<560` la barra se parte en dos filas *(nuevo)*.
- **No se toca el backend**, ni ninguna lectura en su contenido/orden/estilo, ni el array `links` y su lógica de roles (`puede(perfil?.rol, "admin")`).
- **Los 6 tests que ya existen en `Layout.test.tsx` no cambian de aserción.** Si uno falla, el diseño se rompió — no se ajusta el test.
- Las simplificaciones deliberadas con techo conocido llevan un comentario `ponytail:` que nombre el techo y el upgrade.
- **Rama:** `feat/barra-navegacion-plegable` (ya creada). **No se pushea a master sin OK explícito** del dueño del repo: master auto-despliega a producción.
- **Verificación de UI en el navegador antes de pedir el push.** En este repo un cambio de UI con la suite verde ya rompió producción (branch de `DialogoTexto`): jsdom no implementa container queries, así que **ningún test puede ver el comportamiento responsive de este plan**.

---

### Task 1: La navegación se pliega y las lecturas se quedan

**Files:**
- Modify: `web/src/components/Layout.tsx`
- Test: `web/src/components/Layout.test.tsx` (agregar 3 tests al final; no tocar los 6 existentes)

**Interfaces:**
- Consumes: `useLocation` de `react-router-dom`; `ChevronDown` de `lucide-react`; el array `links` y el componente `Lectura` que ya viven en `Layout.tsx`; `cn` de `@/lib/utils`.
- Produces: nada exportado. El cambio es interno al componente `Layout`.

**Estado actual del archivo (leerlo antes de editar):**
- `Layout.tsx:80-90` — el array `links` (con `to`, `label`, `end`, `Icono`, `admin`).
- `Layout.tsx:98` — el contenedor de marca + nav: `flex min-w-0 items-stretch gap-1 @max-[700px]:overflow-x-auto`.
- `Layout.tsx:118-145` — el `<nav aria-label="Secciones">` con el `.map` de los links.
- `Layout.tsx:150-152` — el comentario del orden de sacrificio, que este task deja obsoleto.
- `Layout.tsx:153` — el grupo de lecturas: `flex items-stretch @max-[980px]:hidden`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `web/src/components/Layout.test.tsx`. Nota sobre cómo se consulta el botón: en `/insumos` el texto "Insumos" aparece tres veces (el link, el botón y la etiqueta de la lectura), así que los tests lo buscan por rol y nombre accesible, no por texto suelto.

```tsx
test("el botón de secciones dice en qué sección estás", async () => {
  // Plegada, la barra tiene que seguir diciendo dónde estás — que es lo que en la
  // barra ancha hace el subrayado del NavLink.
  rol = "editor";
  render(
    <MemoryRouter initialEntries={["/insumos"]}>
      <Layout />
    </MemoryRouter>
  );
  const boton = screen.getByRole("button", { name: /secciones/i });
  expect(boton.textContent).toContain("Insumos");
  expect(boton.getAttribute("aria-expanded")).toBe("false");
});

test("en una ruta anidada el botón muestra la sección padre", async () => {
  // Corridas es el único link con end: false, así que /corridas/7 sigue siendo
  // «Corridas». Sin esto, entrar a una corrida dejaría el botón en «Secciones».
  rol = "editor";
  render(
    <MemoryRouter initialEntries={["/corridas/7"]}>
      <Layout />
    </MemoryRouter>
  );
  expect(screen.getByRole("button", { name: /secciones/i }).textContent).toContain(
    "Corridas"
  );
});

test("el botón de secciones abre y cierra el panel", async () => {
  // jsdom no implementa container queries, así que acá no se puede comprobar que el
  // panel esté oculto: lo que se fija es el estado que la CSS consume (aria-expanded).
  rol = "editor";
  render(
    <MemoryRouter initialEntries={["/insumos"]}>
      <Layout />
    </MemoryRouter>
  );
  const boton = screen.getByRole("button", { name: /secciones/i });

  fireEvent.click(boton);
  expect(boton.getAttribute("aria-expanded")).toBe("true");

  // Navegar cierra el panel: si no, queda tapando la pantalla a la que acabás de entrar.
  fireEvent.click(screen.getByRole("link", { name: /APUs/ }));
  expect(boton.getAttribute("aria-expanded")).toBe("false");

  // El panel que el botón controla es el <nav>, no un menú aparte: un segundo menú
  // duplicaría los links y rompería el guard de los 5 destinos.
  expect(boton.getAttribute("aria-controls")).toBe(
    screen.getByRole("navigation").getAttribute("id")
  );
});
```

Y extender el import de vitest/testing-library de la primera línea del archivo para incluir `fireEvent`:

```tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `cd web && npx vitest run src/components/Layout.test.tsx`
Expected: los 3 nuevos FALLAN con `Unable to find an accessible element with the role "button" and name /secciones/i` (el botón todavía no existe). Los **6 existentes siguen pasando**.

- [ ] **Step 3: Implementar**

En `web/src/components/Layout.tsx`:

**3a. Imports.** Extender los dos que ya existen (no agregar líneas nuevas del mismo módulo):

```tsx
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ChevronDown, FileSpreadsheet, Layers, Package, ScrollText, Users } from "lucide-react";
```

**3b. Estado y sección actual.** Después del array `links` (que queda igual), antes del `return`:

```tsx
  const { pathname } = useLocation();
  const [seccionesAbiertas, setSeccionesAbiertas] = useState(false);

  // Navegar cierra el panel: si no, queda tapando la pantalla a la que acabás de entrar.
  useEffect(() => setSeccionesAbiertas(false), [pathname]);

  // Mismo criterio que NavLink: `end: false` (Corridas) matchea sus rutas anidadas
  // (/corridas/7), el resto exige igualdad. Se busca de atrás para adelante para que
  // gane el match más específico si algún día dos links comparten prefijo.
  const activa = [...links].reverse().find(({ to, end }) =>
    end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`)
  );
  const IconoActiva = activa?.Icono ?? Layers;
```

**3c. El botón.** Dentro del contenedor de `Layout.tsx:98`, entre el bloque de la marca y el `<nav>`:

```tsx
            {/* Plegada, la barra tiene que seguir diciendo dónde estás: el botón muestra
                la sección actual, no una hamburguesa. `hidden @max-[980px]:flex` — no
                existe en la barra ancha.

                ponytail: sin clic-afuera ni Esc — abierto queda abierto hasta que se
                vuelve a tocar el botón. Upgrade si al usarlo molesta: el listener de
                `mousedown` en `document` que ya existe en corrida/BuscadorApu.tsx. */}
            <button
              type="button"
              aria-expanded={seccionesAbiertas}
              aria-controls="barra-secciones"
              onClick={() => setSeccionesAbiertas((abierto) => !abierto)}
              className="hidden @max-[980px]:flex items-center gap-2 whitespace-nowrap rounded px-3 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/40"
            >
              <IconoActiva aria-hidden className="size-3.5 shrink-0 opacity-75" />
              {/* El nombre accesible queda "Secciones: Insumos": dice QUÉ es el botón y
                  además contiene el texto visible, que es lo que pide WCAG 2.5.3
                  (Label in Name). Un `aria-label="Secciones"` pelado lo violaría, porque
                  taparía la palabra que el usuario ve. */}
              <span className="sr-only">Secciones: </span>
              <span className="font-semibold text-foreground">
                {activa?.label ?? "Secciones"}
              </span>
              <ChevronDown
                aria-hidden
                className={cn(
                  "size-3.5 shrink-0 opacity-60 transition-transform",
                  seccionesAbiertas && "rotate-180"
                )}
              />
            </button>
```

> Es un `<button>` pelado y no el componente `Button` de `@/components/ui/button` a
> propósito: los `NavLink` de esta barra también son elementos pelados con clases
> propias, porque `items-stretch` y el indicador de activo necesitan control del alto y
> del borde que `Button` no cede. `Button` se sigue usando para Cerrar sesión.

**3d. El `<nav>`.** Reemplazar la etiqueta de apertura de `Layout.tsx:118` por:

```tsx
            <nav
              id="barra-secciones"
              aria-label="Secciones"
              className={cn(
                "flex items-stretch",
                // En angosto deja de ser una fila de la barra y pasa a ser un panel
                // colgado de ella. Los links se renderizan UNA sola vez: no hay copia
                // ancha y copia angosta (dos copias romperían el guard de los 5 links).
                "@max-[980px]:absolute @max-[980px]:left-0 @max-[980px]:top-full @max-[980px]:z-30",
                "@max-[980px]:w-56 @max-[980px]:flex-col @max-[980px]:items-stretch",
                "@max-[980px]:rounded-b @max-[980px]:border @max-[980px]:border-border",
                "@max-[980px]:bg-card @max-[980px]:py-1 @max-[980px]:shadow-md",
                // Ojo: cerrado se oculta SOLO con el modificador. Un `hidden` pelado
                // haría desaparecer el <nav> en los tests, donde las container queries
                // no existen, y se caerían los guards que ya hay.
                seccionesAbiertas ? "@max-[980px]:flex" : "@max-[980px]:hidden"
              )}
            >
```

El `.map` de adentro **no cambia**, con dos salvedades en las clases del `NavLink` y del separador, para que el panel se lea en columna:

- el separador de Admin (`Layout.tsx:125`): agregarle `@max-[980px]:my-1 @max-[980px]:h-px @max-[980px]:w-full` para que pase de barra vertical a línea horizontal;
- el `NavLink` (`Layout.tsx:132`): agregarle `@max-[980px]:border-b-0 @max-[980px]:border-l-2 @max-[980px]:py-1.5` para que el indicador de activo pase del borde inferior al lateral, que es como se lee en una lista vertical.

El `<header>` de `Layout.tsx:96` necesita `relative` para que el `absolute` del panel se cuelgue de la barra:

```tsx
      <header className="@container relative shrink-0 border-b border-border bg-card">
```

**3e. Las lecturas dejan de esconderse.** En `Layout.tsx:153`, quitar `@max-[980px]:hidden` y agregar el escalón de dos filas:

```tsx
              <div className="flex items-stretch @max-[560px]:basis-full @max-[560px]:justify-between">
```

Y para que ese `basis-full` pueda caer a una segunda fila, el contenedor de la barra (`Layout.tsx:97`) necesita `flex-wrap`, y el bloque del usuario (`Layout.tsx:149`) deja de ser `shrink-0` rígido:

```tsx
        <div className="flex min-h-[54px] flex-wrap items-stretch justify-between gap-5 px-[18px] @max-[560px]:py-2">
```

(el `h-[54px]` fijo pasa a `min-h-[54px]`: con dos filas la barra tiene que poder crecer)

> **Ojo con dónde parte de verdad la segunda fila.** `flex-wrap` hace que la barra se
> parta donde el contenido deja de caber, no en un ancho que elijamos: con el nombre de
> la marca ya fuera (<700px), la cuenta da que va a partir sola alrededor de **~665px**.
> El `@max-[560px]:basis-full` no crea el corte, **garantiza el piso**: abajo de 560px las
> lecturas caen enteras a la segunda fila y se reparten a lo ancho, en vez de quedar
> apretadas o cortadas. En Task 2 hay que **anotar el ancho real** en que se ve partir, no
> forzarlo a 560: si parte antes y se ve bien, está bien.

**3f. El comentario del orden de sacrificio** (`Layout.tsx:150-152`) queda al revés de la verdad. Reemplazarlo por:

```tsx
              {/* Orden de sacrificio al angostarse: primero el correo (decorativo), después
                  el nombre de la marca, y al final la barra se parte en dos filas. Las
                  lecturas NO se esconden en ningún ancho — es el punto de la feature. Lo
                  que se pliega es la navegación (ver el botón de secciones arriba). */}
```

- [ ] **Step 4: Correr los tests y el build**

Run: `cd web && npx vitest run src/components/Layout.test.tsx && npm run build`
Expected: 9 tests PASS (los 6 de antes sin tocar + los 3 nuevos) y build limpio.

`npm run build` corre `tsc -b`, que es el que de verdad falla ante un tipo mal puesto. `tsc --noEmit` no alcanza en este repo.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Layout.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): la barra angosta pliega la navegacion en vez de esconder las lecturas"
```

---

### Task 2: Verificación en el navegador

**Files:** ninguno (verificación; si algo se ve mal, se arregla acá)

Este task existe porque **jsdom no implementa container queries**: los 9 tests de Task 1 corren siempre contra la versión ancha de la barra, así que ninguno puede ver lo único que este plan cambia. La verificación real es visual.

- [ ] **Step 1: Suite completa del frontend**

Run: `cd web && npx vitest run && npm run build`
Expected: 180 tests PASS (177 de hoy + 3 nuevos), build limpio con los dos warnings de vite preexistentes (import dinámico de `supabase.ts`, chunk >500 kB).

- [ ] **Step 2: Levantar la web en local**

Necesita `SUPABASE_URL` + `APU_ADMIN_EMAILS` en el entorno; sin eso todo `/api` rebota con 401 y no se llega ni al Layout.

- [ ] **Step 3: Verificar los cuatro escalones con el DevTools**

Usar el modo responsive del navegador (o arrastrar la ventana) y comprobar, en este orden:

| Ancho | Qué tiene que pasar |
|---|---|
| 1400px | Todo igual que hoy: secciones en fila, correo visible, 4 lecturas. **No hay botón de secciones.** |
| 1100px | Se fue el correo. Todo lo demás igual, sin botón. |
| 900px | **Aparece el botón** con el ícono y el nombre de la sección actual. Las secciones ya no están en fila. **Las 4 lecturas siguen visibles** (esto es lo que antes desaparecía). |
| 650px | Se fue el nombre "Armador de APUs". Botón y lecturas siguen. |
| 400px | La barra está en dos filas: arriba logo + botón + rol + Cerrar sesión; abajo las 4 lecturas repartidas a lo ancho. Nada tapado, nada cortado. |

Y anotar **el ancho exacto en que se ve partir en dos filas**: el `flex-wrap` parte donde
el contenido deja de caber (la cuenta da ~665px), y el `@max-[560px]` es solo el piso
garantizado. Si parte antes de 560 y se ve bien, está bien — es el dato que hay que
reportar, no un problema que haya que forzar.

- [ ] **Step 4: Verificar el panel a 900px**

1. Clic en el botón → se abre el panel colgado de la barra, en columna, con las 5 secciones (siendo admin) y el separador del grupo Admin como línea horizontal.
2. La sección actual se ve marcada dentro del panel.
3. Clic en otra sección → navega **y el panel se cierra**.
4. El panel no queda tapado por la tabla de la página ni se corta contra el borde.
5. Con el teclado: Tab llega al botón, Enter y Espacio lo abren, Tab recorre las secciones.
6. Volver a hacer clic en el botón lo cierra.

- [ ] **Step 5: Confirmar el techo conocido**

Clic en el botón para abrir y después clic en cualquier lugar de la página: el panel **queda abierto** (no hay clic-afuera, es deliberado). Si al usarlo molesta, el upgrade es el listener de `mousedown` en `document` que ya existe en `web/src/components/corrida/BuscadorApu.tsx:26-34` — decidirlo acá, con el navegador delante, no antes.

- [ ] **Step 6: Reportar y pedir el OK para el push**

Reportar al dueño del repo: la salida real de la suite, la tabla de escalones punto por punto con lo que se vio, y si el panel sin clic-afuera molestó o no. **No pushear a master sin OK explícito.**

---

## Notas para quien implementa

- **Un solo `<nav>`.** Si te encontrás escribiendo un segundo menú para la versión angosta, pará: es exactamente lo que este plan evita, y el test `la navegación es un landmark…` lo va a atrapar con 10 links en vez de 5.
- **No ajustes los 6 tests existentes.** Si uno se pone rojo, lo que está mal es el cambio, no el test.
- **No agregues `@min-[…]`.** Todo el archivo usa `@max-[…]`; mezclar los dos criterios en la misma barra es cómo se cuelan huecos entre escalones.
- Si un ancho intermedio queda feo (algo se corta, dos cosas se pisan), reportalo con el ancho exacto en vez de inventar un escalón nuevo: los cortes salieron de una cuenta que está en la spec y cambiarlos es una decisión, no un ajuste.
