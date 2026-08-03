> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-03-dialogo-texto-sin-prompt.md`

# Un modal propio en lugar de `window.prompt()` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar los 6 `window.prompt()` que piden un nombre por un modal propio, accesible y consistente con el resto de la app.

**Architecture:** Un componente nuevo `DialogoTexto` construido sobre el `Dialog` que ya usa el repo (Radix, `components/ui/dialog.tsx`), con un input, Cancelar y Confirmar. Cada llamador pasa de imperativo (`const x = prompt(); if (!x) return; await api(x)`) a declarativo (estado de "qué diálogo está abierto" + el modal renderizado + `onConfirmar`). Los handlers conservan su lógica actual íntegra, incluidos los detalles no obvios (auto-selección tras crear, "si el nombre no cambió no llames a la API", `toast.success`, `stopPropagation`).

**Tech Stack:** React 19, TypeScript, Radix Dialog vía `components/ui/dialog.tsx`, Vitest + Testing Library. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-03-dialogo-texto-sin-prompt-design.md`

## Global Constraints

- **Español** en nombres de componente/props, comentarios y textos de usuario.
- **Ningún cambio en el backend**: mismos endpoints, mismos payloads, ni un archivo `.py`.
- **NO tocar** los 3 `window.confirm` (`Insumos.tsx:99` guard de precios sin guardar — es de dinero y su test flaquea; `MisCorridas.tsx:105` eliminar corrida; `MisCorridas.tsx:140` eliminar carpeta).
- **NO tocar** los 2 `window.prompt` de "escribe el número" (`MisCorridas.tsx:170` mover corrida, `:194` mover carpeta): son elegir de una lista, no escribir texto, y necesitan otro diseño.
- **NO tocar** `Insumos.dirty.test.tsx`.
- **El botón de confirmar queda HABILITADO con el campo vacío** y muestra *"Escribí un nombre"*. Es deliberado y hay que dejarlo comentado en el código: rompe el patrón de `DialogoAgregarApu` (`disabled={!valido || guardando}`) a propósito, por la misma razón que el commit `6fd5472` sacó el `disabled` del botón "Armar" — un botón bloqueado sin explicación deja al usuario sin salida.
- **Los llamadores conservan su `toast.error`** y además **re-lanzan** el error, para que el diálogo quede abierto con lo escrito. Así los tests que afirman el toast siguen valiendo y se gana poder corregir sin reescribir.
- `pytest` no se usa acá. Los comandos del frontend se corren desde `web/`: `npx vitest run`, `npm run build`, `npx oxlint`.
- Rama: `feat/dialogo-texto-sin-prompt` (ya creada, con el spec commiteado).

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `web/src/components/DialogoTexto.tsx` | El modal reutilizable: un input, validación de vacío, Enter/Esc, y "queda abierto si falla". No conoce ningún dominio. | Crear (Task 1) |
| `web/src/components/DialogoTexto.test.tsx` | Comportamiento del componente aislado. | Crear (Task 1) |
| `web/src/pages/Insumos.tsx` | 2 usos: crear y renombrar lista de precios. | Modificar (Task 2) |
| `web/src/pages/Insumos.listas.test.tsx` | Hoy stubbea `window.prompt`; pasa a interactuar con el modal. | Modificar (Task 2) |
| `web/src/pages/CorridasInicio.tsx` | 1 uso: crear carpeta/subcarpeta. | Modificar (Task 3) |
| `web/src/pages/CorridasInicio.test.tsx` | Test nuevo del flujo con modal. | Modificar (Task 3) |
| `web/src/pages/MisCorridas.tsx` | 3 usos: nueva carpeta, renombrar carpeta, renombrar corrida. | Modificar (Task 4) |
| `web/src/pages/MisCorridas.test.tsx` | Hoy stubbea `window.prompt`; pasa a interactuar con el modal. | Modificar (Task 4) |

---

### Task 1: El componente `DialogoTexto`

**Files:**
- Create: `web/src/components/DialogoTexto.tsx`
- Create: `web/src/components/DialogoTexto.test.tsx`

**Interfaces:**
- Consumes: `Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle` de `@/components/ui/dialog`; `Button` de `@/components/ui/button`; `Input` de `@/components/ui/input`. Los tres ya existen y los usa `components/insumos/DialogoImportarInsumos.tsx`.
- Produces — las Tasks 2, 3 y 4 importan exactamente esto:
  ```ts
  export function DialogoTexto(props: {
    open: boolean;
    onOpenChange: (v: boolean) => void;
    titulo: string;
    etiqueta?: string;          // "Nombre" por defecto
    valorInicial?: string;      // "" por defecto
    ayuda?: string;
    textoConfirmar?: string;    // "Guardar" por defecto
    onConfirmar: (valor: string) => void | Promise<void>;
  }): JSX.Element
  ```
  El `id` del input es `dialogo-texto-valor` y su `<label>` usa `htmlFor` — los tests lo buscan con `getByLabelText`.

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/components/DialogoTexto.test.tsx`:

```tsx
/**
 * El modal que reemplaza a `window.prompt()` (hallazgo 3 del smoke test de producción
 * del 2026-08-03: el prompt nativo no se puede estilizar, no es accesible y bloquea el
 * hilo de la página).
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { DialogoTexto } from "./DialogoTexto";

function abrir(props: Partial<React.ComponentProps<typeof DialogoTexto>> = {}) {
  const onConfirmar = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <DialogoTexto
      open
      onOpenChange={onOpenChange}
      titulo="Nueva lista de precios"
      onConfirmar={onConfirmar}
      {...props}
    />
  );
  return { onConfirmar, onOpenChange };
}

test("muestra el título y enfoca el input al abrir", async () => {
  abrir();
  expect(screen.getByText("Nueva lista de precios")).toBeTruthy();
  const input = screen.getByLabelText("Nombre") as HTMLInputElement;
  await waitFor(() => expect(document.activeElement).toBe(input));
});

test("precarga el valor inicial (caso renombrar)", () => {
  abrir({ valorInicial: "NP Calle 13", textoConfirmar: "Guardar" });
  expect((screen.getByLabelText("Nombre") as HTMLInputElement).value).toBe("NP Calle 13");
});

test("confirma con el valor recortado y cierra", async () => {
  const { onConfirmar, onOpenChange } = abrir({ textoConfirmar: "Crear" });
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "  NP Peñón  " } });
  fireEvent.click(screen.getByRole("button", { name: "Crear" }));

  await waitFor(() => expect(onConfirmar).toHaveBeenCalledWith("NP Peñón"));
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});

test("Enter en el input confirma", async () => {
  const { onConfirmar } = abrir({ textoConfirmar: "Crear" });
  const input = screen.getByLabelText("Nombre");
  fireEvent.change(input, { target: { value: "NP Peñón" } });
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(onConfirmar).toHaveBeenCalledWith("NP Peñón"));
});

test("vacío: avisa y NO confirma, con el botón habilitado", async () => {
  const { onConfirmar, onOpenChange } = abrir({ textoConfirmar: "Crear" });
  const btn = screen.getByRole("button", { name: "Crear" });
  expect(btn.hasAttribute("disabled")).toBe(false);   // a propósito: ver el spec

  fireEvent.click(btn);

  await waitFor(() => expect(screen.getByText("Escribí un nombre")).toBeTruthy());
  expect(onConfirmar).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalled();        // no cierra
});

test("solo espacios cuenta como vacío", async () => {
  const { onConfirmar } = abrir({ textoConfirmar: "Crear" });
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "   " } });
  fireEvent.click(screen.getByRole("button", { name: "Crear" }));
  await waitFor(() => expect(screen.getByText("Escribí un nombre")).toBeTruthy());
  expect(onConfirmar).not.toHaveBeenCalled();
});

test("si onConfirmar falla, el diálogo NO cierra y conserva lo escrito", async () => {
  const onOpenChange = vi.fn();
  const onConfirmar = vi.fn(() => Promise.reject(new Error("Ya existe una lista así")));
  render(
    <DialogoTexto open onOpenChange={onOpenChange} titulo="Nueva lista"
                  textoConfirmar="Crear" onConfirmar={onConfirmar} />
  );
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "NP Calle 13" } });
  fireEvent.click(screen.getByRole("button", { name: "Crear" }));

  await waitFor(() => expect(onConfirmar).toHaveBeenCalled());
  expect(onOpenChange).not.toHaveBeenCalledWith(false);
  expect((screen.getByLabelText("Nombre") as HTMLInputElement).value).toBe("NP Calle 13");
});

test("Cancelar cierra sin confirmar", () => {
  const { onConfirmar, onOpenChange } = abrir();
  fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(onConfirmar).not.toHaveBeenCalled();
});

test("muestra el texto de ayuda cuando se pasa", () => {
  abrir({ ayuda: "Nombrála con la obra, p. ej. «NP Calle 13»." });
  expect(screen.getByText("Nombrála con la obra, p. ej. «NP Calle 13».")).toBeTruthy();
});
```

**Nota deliberada sobre Esc:** cerrar con Escape lo da Radix (`DialogContent`), no este
componente, así que no se testea acá — sería testear la librería, y en jsdom ese camino
depende de la configuración de pointer events. Lo que sí se testea es el botón Cancelar,
que es código nuestro.

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/components/DialogoTexto.test.tsx`
Expected: FAIL — `Failed to resolve import "./DialogoTexto"` (el componente todavía no existe).

- [ ] **Step 3: Crear el componente**

Crear `web/src/components/DialogoTexto.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  titulo: string;
  etiqueta?: string;
  valorInicial?: string;
  ayuda?: string;
  textoConfirmar?: string;
  onConfirmar: (valor: string) => void | Promise<void>;
};

/**
 * Pide un texto (un nombre) en un modal propio, en lugar de `window.prompt()`.
 *
 * El prompt nativo no se puede estilizar, no es accesible y bloquea el hilo principal de
 * la página (hallazgo 3 del smoke test de producción del 2026-08-03). Este componente no
 * conoce ningún dominio: el llamador pone el título, la ayuda y qué hacer al confirmar.
 */
export function DialogoTexto({
  open,
  onOpenChange,
  titulo,
  etiqueta = "Nombre",
  valorInicial = "",
  ayuda,
  textoConfirmar = "Guardar",
  onConfirmar,
}: Props) {
  const [valor, setValor] = useState(valorInicial);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);

  // Cada apertura arranca limpia y con el valor inicial: al renombrar, precargado con el
  // nombre actual, igual que hacía el segundo argumento de window.prompt().
  useEffect(() => {
    if (open) {
      setValor(valorInicial);
      setError(null);
    }
  }, [open, valorInicial]);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    const limpio = valor.trim();
    // El botón queda HABILITADO con el campo vacío y avisa acá. Es deliberado y rompe el
    // patrón de DialogoAgregarApu (`disabled={!valido}`): un botón bloqueado sin
    // explicación deja al usuario sin salida — es lo que se arregló en el commit 6fd5472.
    if (!limpio) {
      setError("Escribí un nombre");
      return;
    }
    setGuardando(true);
    try {
      await onConfirmar(limpio);
      onOpenChange(false);
    } catch {
      // El llamador ya mostró su toast con el mensaje del backend y re-lanzó. Dejamos el
      // diálogo abierto con lo escrito para poder corregir: el prompt nativo cerraba y
      // había que reescribir el nombre desde cero (p. ej. una lista duplicada -> 400).
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">{titulo}</DialogTitle>
        </DialogHeader>
        <form onSubmit={confirmar} className="space-y-2">
          <label className="text-xs block" htmlFor="dialogo-texto-valor">
            {etiqueta}
          </label>
          <Input
            id="dialogo-texto-valor"
            autoFocus
            value={valor}
            onChange={(e) => {
              setValor(e.target.value);
              setError(null);
            }}
          />
          {ayuda && <p className="text-xs text-muted-foreground">{ayuda}</p>}
          {error && <p className="text-xs text-red-600">{error}</p>}
          <DialogFooter>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={guardando}
            >
              Cancelar
            </Button>
            <Button type="submit" size="sm" disabled={guardando}>
              {guardando ? "Guardando…" : textoConfirmar}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Correr los tests**

Run: `cd web && npx vitest run src/components/DialogoTexto.test.tsx`
Expected: PASS, 9 tests.

Si el test del foco falla, es porque el `autoFocus` de Radix compite con el del input: en ese caso agregá un `useEffect` que enfoque por `ref` cuando `open` pasa a true, y dejá el comentario explicando por qué.

- [ ] **Step 5: Suite completa del frontend**

Run: `cd web && npx vitest run`
Expected: PASS. Referencia antes de esta task: 128 passed.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/DialogoTexto.tsx web/src/components/DialogoTexto.test.tsx
git commit -m "feat(web): componente DialogoTexto para reemplazar window.prompt()"
```

---

### Task 2: `Insumos` — crear y renombrar lista de precios

**Files:**
- Modify: `web/src/pages/Insumos.tsx` (handlers `crearListaNueva` ~línea 110 y `renombrarListaActual` ~línea 127)
- Modify: `web/src/pages/Insumos.listas.test.tsx`

**Interfaces:**
- Consumes: `DialogoTexto` de Task 1, con la firma del bloque "Produces" de esa task.
- Produces: nada para otras tasks.

- [ ] **Step 1: Escribir/ajustar los tests que fallan**

En `web/src/pages/Insumos.listas.test.tsx`, los tests que hoy hacen
`vi.spyOn(window, "prompt").mockReturnValue("NP Peñón")` pasan a interactuar con el modal.
Reemplazá esos tres tests por estos (el resto del archivo no se toca):

```tsx
  it("un editor puede crear una lista y queda seleccionado en ella", async () => {
    crearLista.mockResolvedValue({ id: 3, nombre: "NP Peñón", creada_en: "2026-07-28" });

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalledTimes(1));
    expect(listarInsumos.mock.calls[0][0].lista).toBe(1);
    expect(listarListas).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("+ Nueva"));
    // Ya no hay prompt nativo: se escribe en el modal.
    fireEvent.change(await screen.findByLabelText("Nombre"), {
      target: { value: "NP Peñón" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() => expect(crearLista).toHaveBeenCalledWith("NP Peñón"));
    await waitFor(() => expect(listarListas.mock.calls.length).toBeGreaterThan(1));
  });

  it("cancelar el diálogo no crea ninguna lista", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());

    fireEvent.click(screen.getByText("+ Nueva"));
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));

    expect(crearLista).not.toHaveBeenCalled();
  });

  it("un 400 del backend (nombre duplicado) al crear muestra el mensaje del backend", async () => {
    crearLista.mockRejectedValue(
      new Error("Ya existe una lista de precios llamada «NP Calle 13».")
    );

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());

    fireEvent.click(screen.getByText("+ Nueva"));
    fireEvent.change(await screen.findByLabelText("Nombre"), {
      target: { value: "NP Calle 13" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Ya existe una lista de precios llamada «NP Calle 13»."
      ));
    // El diálogo queda abierto con lo escrito, para corregir sin reescribir.
    expect((screen.getByLabelText("Nombre") as HTMLInputElement).value).toBe("NP Calle 13");
  });
```

Si el archivo no importaba `toast`, agregá el import del mock que ya usa (`import { toast } from "sonner";`) y confirmá que `sonner` esté mockeado en ese archivo; si no lo está, agregá
`vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));` junto a los otros mocks del archivo.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/pages/Insumos.listas.test.tsx`
Expected: FAIL — al hacer clic en "+ Nueva" no aparece ningún modal, así que
`findByLabelText("Nombre")` da timeout (`Unable to find a label with the text of: Nombre`).

- [ ] **Step 3: Convertir los dos handlers en `Insumos.tsx`**

3a. Importar el componente junto a los otros imports del archivo:

```tsx
import { DialogoTexto } from "@/components/DialogoTexto";
```

3b. Agregar el estado del diálogo, al lado de los otros `useState` de la página:

```tsx
  // Qué diálogo de texto está abierto. Antes esto era window.prompt() (imperativo);
  // ahora el modal es declarativo y necesita saber qué se está pidiendo.
  const [dialogo, setDialogo] = useState<"crear-lista" | "renombrar-lista" | null>(null);
```

3c. Reemplazar el cuerpo de `crearListaNueva` y `renombrarListaActual`. Los comentarios que
ya tienen arriba (los que explican la auto-selección y el guard de cambios sin guardar) **se
conservan tal cual**:

```tsx
  async function crearListaNueva(nombre: string) {
    try {
      const nueva = await crearLista(nombre);
      await cargarListas();
      cambiarFiltros({ lista: nueva.id, fuente: "", clasificacion: "", sinPrecio: false, offset: 0 });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "No se pudo crear la lista de precios";
      toast.error(msg);
      throw e;   // el diálogo queda abierto para corregir el nombre
    }
  }

  async function renombrarListaActual(nombre: string) {
    try {
      await renombrarLista(filtros.lista, nombre);
      await cargarListas();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "No se pudo renombrar la lista de precios";
      toast.error(msg);
      throw e;   // el diálogo queda abierto para corregir el nombre
    }
  }
```

3d. Los props de `BarraFiltros` pasan a abrir el diálogo en vez de ejecutar el handler
(líneas ~189-190). La Principal no se renombra: ese guard estaba dentro del handler viejo y
ahora vive en el `onRenombrarLista`:

```tsx
        onCrearLista={() => setDialogo("crear-lista")}
        onRenombrarLista={() => {
          if (filtros.lista === LISTA_PRINCIPAL_ID) return;   // la Principal no se renombra
          setDialogo("renombrar-lista");
        }}
```

3e. Renderizar los dos diálogos al final del JSX de la página, dentro del contenedor
principal (junto a los otros diálogos que ya se renderizan ahí):

```tsx
      <DialogoTexto
        open={dialogo === "crear-lista"}
        onOpenChange={(v) => setDialogo(v ? "crear-lista" : null)}
        titulo="Nueva lista de precios"
        ayuda="Nombrála con la obra, p. ej. «NP Calle 13»."
        textoConfirmar="Crear"
        onConfirmar={crearListaNueva}
      />
      <DialogoTexto
        open={dialogo === "renombrar-lista"}
        onOpenChange={(v) => setDialogo(v ? "renombrar-lista" : null)}
        titulo="Renombrar lista de precios"
        valorInicial={listaActivaNombre}
        textoConfirmar="Guardar"
        onConfirmar={renombrarListaActual}
      />
```

`listaActivaNombre` ya existe en el archivo (`listas.find(...)?.nombre ?? "Principal"`).

- [ ] **Step 4: Correr los tests del archivo**

Run: `cd web && npx vitest run src/pages/Insumos.listas.test.tsx`
Expected: PASS, todos.

- [ ] **Step 5: Confirmar que no quedó ningún prompt en esta pantalla y que el guard de dinero sigue intacto**

Run: `cd web && grep -n "window.prompt\|window.confirm" src/pages/Insumos.tsx`
Expected: **solo** la línea del `window.confirm` (~99), el guard de precios sin guardar. Cero `window.prompt`.

Run: `cd web && npx vitest run src/pages/Insumos.dirty.test.tsx`
Expected: PASS, 2 tests (no se tocó, pero es el que cubre ese guard).

- [ ] **Step 6: Suite completa**

Run: `cd web && npx vitest run`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/Insumos.tsx web/src/pages/Insumos.listas.test.tsx
git commit -m "feat(web): crear y renombrar listas de precios con DialogoTexto"
```

---

### Task 3: `CorridasInicio` — crear carpeta y subcarpeta

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx` (`handleCrearCarpeta`, líneas 63-88)
- Modify: `web/src/pages/CorridasInicio.test.tsx`

**Interfaces:**
- Consumes: `DialogoTexto` de Task 1.
- Produces: nada.

Contexto que hay que preservar: el título depende de si hay carpeta de nivel 1 seleccionada
(carpeta vs subcarpeta) y, tras crear, **se auto-selecciona** la nueva (nivel 2 si era
subcarpeta, nivel 1 si era raíz).

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `web/src/pages/CorridasInicio.test.tsx`. El archivo ya mockea
`@/api/carpetas`; hay que asegurarse de que `crearCarpeta` sea un mock inspeccionable —
si está como `crearCarpeta: vi.fn()`, exportalo con `vi.hoisted` igual que `armarArchivoMock`
y usalo acá:

```tsx
test("crear carpeta usa el modal y auto-selecciona la nueva", async () => {
  crearCarpetaMock.mockResolvedValue({ id: 9, nombre: "Obra Nueva", parent_id: null, n_corridas: 0, hijas: [] });
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getByRole("button", { name: "+ Carpeta" }));
  fireEvent.change(await screen.findByLabelText("Nombre"), { target: { value: "Obra Nueva" } });
  fireEvent.click(screen.getByRole("button", { name: "Crear" }));

  await waitFor(() => expect(crearCarpetaMock).toHaveBeenCalledWith("Obra Nueva", null));
});
```

El botón se llama literalmente **`+ Carpeta`** (`CorridasInicio.tsx:235`, `onClick={handleCrearCarpeta}`).

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/pages/CorridasInicio.test.tsx`
Expected: FAIL — no aparece el modal, `findByLabelText("Nombre")` da timeout.

- [ ] **Step 3: Convertir el handler**

3a. Importar: `import { DialogoTexto } from "@/components/DialogoTexto";`

3b. Estado: `const [pidiendoCarpeta, setPidiendoCarpeta] = useState(false);`

3c. Reemplazar `handleCrearCarpeta` (que hoy arranca con `window.prompt`) por una versión
que recibe el nombre ya validado, conservando **toda** la lógica de auto-selección:

```tsx
  async function handleCrearCarpeta(nombre: string) {
    try {
      const nueva = await crearCarpeta(nombre, nivel1Id);
      const arbol = await cargarCarpetas();
      // Auto-select the new folder as destination
      if (nivel1Id !== null) {
        // Created a subfolder under the current level-1
        setNivel2Id(nueva.id);
      } else {
        // Created a new level-1 folder; select it
        const nodo = arbol.find((c) => c.id === nueva.id);
        if (nodo) {
          setNivel1Id(nueva.id);
          setNivel2Id(null);
        }
      }
    } catch {
      toast.error("No se pudo crear la carpeta");
      throw new Error("no se pudo crear la carpeta");   // el diálogo queda abierto
    }
  }
```

3d. El botón que antes llamaba a `handleCrearCarpeta` ahora abre el diálogo:
`onClick={() => setPidiendoCarpeta(true)}`.

3e. Renderizar el diálogo dentro del JSX de la página, después del `</form>`:

```tsx
      <DialogoTexto
        open={pidiendoCarpeta}
        onOpenChange={setPidiendoCarpeta}
        titulo={nivel1Id !== null ? "Nueva subcarpeta" : "Nueva carpeta"}
        textoConfirmar="Crear"
        onConfirmar={handleCrearCarpeta}
      />
```

- [ ] **Step 4: Correr los tests del archivo**

Run: `cd web && npx vitest run src/pages/CorridasInicio.test.tsx`
Expected: PASS, todos (los 7 anteriores + el nuevo).

- [ ] **Step 5: Confirmar que no quedan prompts acá**

Run: `cd web && grep -c "window.prompt" src/pages/CorridasInicio.tsx`
Expected: `0`.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/pages/CorridasInicio.test.tsx
git commit -m "feat(web): crear carpeta desde Nueva corrida con DialogoTexto"
```

---

### Task 4: `MisCorridas` — nueva carpeta, renombrar carpeta y renombrar corrida

**Files:**
- Modify: `web/src/pages/MisCorridas.tsx` (`handleNuevaCarpeta` 115-124, `handleRenombrar` 126-136, `handleRenombrarCorrida` 148-160)
- Modify: `web/src/pages/MisCorridas.test.tsx`

**Interfaces:**
- Consumes: `DialogoTexto` de Task 1.
- Produces: nada.

Contexto que hay que preservar, y es lo más fácil de perder:
- `handleRenombrar` y `handleRenombrarCorrida` **no llaman a la API si el nombre no cambió**
  (`nuevo.trim() === carpeta.nombre → return`).
- `handleRenombrarCorrida` hace `toast.success(\`Corrida renombrada a "${nuevo}"\`)`.
- Los tres handlers de fila reciben un `React.MouseEvent` y hacen `e.stopPropagation()`
  (la fila es clickeable): **el `stopPropagation` se queda en el `onClick` del botón**, no
  puede irse al `onConfirmar`.

- [ ] **Step 1: Escribir/ajustar los tests que fallan**

Botones que disparan cada diálogo, para los `getBy...`:
- **nueva carpeta**: texto `Nueva carpeta` (`MisCorridas.tsx:234`)
- **renombrar carpeta**: `title="Renombrar carpeta"`, texto `Renombrar` (`:291-293`)
- **renombrar corrida**: `title="Renombrar corrida"` (`:394`) — usar `getByTitle`, porque el
  botón de fila puede no tener texto propio.

En `web/src/pages/MisCorridas.test.tsx`, los tests que stubbean `window.prompt` pasan a
interactuar con el modal. Para cada uno: clic en el botón que abría el prompt, luego

```tsx
  fireEvent.change(await screen.findByLabelText("Nombre"), { target: { value: "<nuevo>" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
```

y la misma aserción sobre la llamada a la API que ya tenía el test. Agregá además este test
nuevo, que fija la regla que más fácil se rompe al refactorizar:

```tsx
test("renombrar con el mismo nombre no llama a la API", async () => {
  render(<MemoryRouter><MisCorridas /></MemoryRouter>);
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getAllByTitle("Renombrar carpeta")[0]);
  // El modal viene precargado con el nombre actual: confirmar sin cambiarlo no debe hacer nada.
  fireEvent.click(await screen.findByRole("button", { name: "Guardar" }));

  await waitFor(() => expect(screen.queryByLabelText("Nombre")).toBeNull());
  expect(renombrarCarpetaMock).not.toHaveBeenCalled();
});
```

Ajustá los nombres de los mocks (`renombrarCarpetaMock`, etc.) a cómo estén declarados en
ese archivo; si están como `vi.fn()` dentro del `vi.mock`, sacalos con `vi.hoisted` para
poder inspeccionarlos, igual que `armarArchivoMock` en `CorridasInicio.test.tsx`.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: FAIL — no aparece ningún modal (`Unable to find a label with the text of: Nombre`).

- [ ] **Step 3: Convertir los tres handlers**

3a. Importar: `import { DialogoTexto } from "@/components/DialogoTexto";`

3b. Un solo estado con unión discriminada (no tres banderas):

```tsx
  // Qué se está pidiendo por modal. Antes eran tres window.prompt() imperativos.
  type Pedido =
    | { tipo: "nueva-carpeta" }
    | { tipo: "renombrar-carpeta"; id: number; nombre: string }
    | { tipo: "renombrar-corrida"; id: number; nombre: string };
  const [pedido, setPedido] = useState<Pedido | null>(null);
```

3c. Los tres handlers pasan a recibir el nombre ya validado:

```tsx
  async function crearCarpetaConNombre(nombre: string) {
    try {
      await crearCarpeta(nombre, carpetaActual);
      cargar();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Error al crear carpeta");
      throw e;
    }
  }

  async function renombrarCarpetaConNombre(id: number, actual: string, nuevo: string) {
    if (nuevo === actual) return;      // no llamamos a la API si no cambió
    try {
      await renombrarCarpeta(id, nuevo);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al renombrar");
      throw err;
    }
  }

  async function renombrarCorridaConNombre(id: number, actual: string, nuevo: string) {
    if (nuevo === actual) return;      // no llamamos a la API si no cambió
    try {
      await renombrarCorrida(id, nuevo);
      toast.success(`Corrida renombrada a "${nuevo}"`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al renombrar");
      throw err;
    }
  }
```

3d. Los `onClick` de los botones abren el diálogo y **conservan el `stopPropagation`**:

```tsx
  // Nueva carpeta (botón de la barra):
  onClick={() => setPedido({ tipo: "nueva-carpeta" })}

  // Renombrar carpeta (botón de fila):
  onClick={(e) => {
    e.stopPropagation();
    setPedido({ tipo: "renombrar-carpeta", id: carpeta.id, nombre: carpeta.nombre });
  }}

  // Renombrar corrida (botón de fila):
  onClick={(e) => {
    e.stopPropagation();
    setPedido({ tipo: "renombrar-corrida", id: corrida.id, nombre: corrida.nombre });
  }}
```

3e. Un solo `DialogoTexto` al final del JSX, manejando los tres casos:

```tsx
      <DialogoTexto
        open={pedido !== null}
        onOpenChange={(v) => { if (!v) setPedido(null); }}
        titulo={
          pedido?.tipo === "nueva-carpeta" ? "Nueva carpeta"
            : pedido?.tipo === "renombrar-carpeta" ? "Renombrar carpeta"
              : "Renombrar corrida"
        }
        valorInicial={pedido && pedido.tipo !== "nueva-carpeta" ? pedido.nombre : ""}
        textoConfirmar={pedido?.tipo === "nueva-carpeta" ? "Crear" : "Guardar"}
        onConfirmar={async (valor) => {
          if (!pedido) return;
          if (pedido.tipo === "nueva-carpeta") await crearCarpetaConNombre(valor);
          else if (pedido.tipo === "renombrar-carpeta")
            await renombrarCarpetaConNombre(pedido.id, pedido.nombre, valor);
          else await renombrarCorridaConNombre(pedido.id, pedido.nombre, valor);
        }}
      />
```

- [ ] **Step 4: Correr los tests del archivo**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: PASS, todos.

- [ ] **Step 5: Confirmar qué quedó nativo (debe ser exactamente lo de fuera de alcance)**

Run: `cd web && grep -n "window.prompt\|window.confirm" src/pages/MisCorridas.tsx`
Expected: **exactamente 4 líneas** — los 2 `window.confirm` de eliminar (corrida y carpeta) y
los 2 `window.prompt` de "Escribe el número" (mover corrida y mover carpeta). Ningún otro.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/MisCorridas.tsx web/src/pages/MisCorridas.test.tsx
git commit -m "feat(web): nueva carpeta y renombrar (carpeta/corrida) con DialogoTexto"
```

---

### Task 5: Verificación final

**Files:** ninguno (solo verificación). Si algo falla, se corrige en la task que corresponda.

**Interfaces:** Consumes todo lo anterior. Produces nada.

- [ ] **Step 1: Inventario de diálogos nativos**

Run: `cd web && grep -rn "window.prompt\|window.confirm" --include="*.tsx" src/ | grep -v "\.test\."`
Expected: **exactamente 5 líneas** —
`Insumos.tsx` el `confirm` del guard de precios sin guardar;
`MisCorridas.tsx` los 2 `confirm` de eliminar y los 2 `prompt` de "Escribe el número".
Cero `window.prompt` en `Insumos.tsx` y en `CorridasInicio.tsx`.

- [ ] **Step 2: Los 3 pasos del job de frontend, tres veces la suite**

`Insumos.dirty.test.tsx` flaquea ~1 de cada 18 corridas por contención de máquina (por eso
`vitest.config.ts` tiene `testTimeout: 10_000`), así que la suite se corre 3 veces:

```bash
cd web && for i in 1 2 3; do npx vitest run; done && npm run build && npx oxlint
```
Expected: las 3 corridas en verde, build OK, oxlint exit 0.

- [ ] **Step 3: El backend, aunque no se tocó**

Run: `python -m pytest tests/ -q` (desde la raíz del repo)
Expected: PASS. Sin `TEST_DATABASE_URL` verás 15 skipped, que es lo esperado.

Run: `git diff --stat master..HEAD -- '*.py'`
Expected: vacío — esta rama no toca ni un archivo Python.

- [ ] **Step 4: Commit (solo si hubo que ajustar algo)**

```bash
git add -A && git commit -m "test: verificación final del reemplazo de window.prompt"
```

---

## Antes de mergear

1. Los 4 pasos de `.github/workflows/ci.yml` en verde localmente (Task 5).
2. Revisión del diff completo: `git diff master...feat/dialogo-texto-sin-prompt`.
3. **Aprobación explícita del usuario** antes de mergear y antes de pushear: `master`
   auto-despliega a producción en Render.
4. No hay migración ni paso manual en Supabase: esta rama no toca el backend.
5. Pendiente conocido que esta rama NO cierra: los 2 `prompt` de "Escribe el número" para
   mover corrida/carpeta necesitan un selector, no un cuadro de texto.
