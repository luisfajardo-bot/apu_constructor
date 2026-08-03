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

// H1: window.prompt(msg, default) preseleccionaba el valor por defecto (escribís y
// lo reemplazás). autoFocus por sí solo deja el caret al principio, así que escribir
// ANTEPONÍA al nombre viejo en vez de reemplazarlo. Fija la preselección al foco.
test("al enfocar con un valor precargado, el texto queda seleccionado (no solo con el caret al inicio)", async () => {
  abrir({ valorInicial: "Calle 13" });
  const input = screen.getByLabelText("Nombre") as HTMLInputElement;
  await waitFor(() => expect(document.activeElement).toBe(input));
  expect(input.selectionStart).toBe(0);
  expect(input.selectionEnd).toBe("Calle 13".length);
});

// H2: los 9 tests de arriba montan con `open` ya en `true`, así que nadie ejercitaba
// el useEffect que resetea `valor` al reabrir. Ese efecto es lo único que evita que el
// DialogoTexto COMPARTIDO de MisCorridas.tsx muestre el nombre de la entidad anterior
// al abrirse para otra.
test("al reabrir con un valorInicial distinto, el input muestra el nuevo (no el de la apertura previa)", async () => {
  const onConfirmar = vi.fn();
  const onOpenChange = vi.fn();
  const { rerender } = render(
    <DialogoTexto
      open
      onOpenChange={onOpenChange}
      titulo="Renombrar carpeta"
      valorInicial="Calle 13"
      onConfirmar={onConfirmar}
    />
  );
  expect((screen.getByLabelText("Nombre") as HTMLInputElement).value).toBe("Calle 13");

  // Cierra (como haría el llamador tras confirmar/cancelar)
  rerender(
    <DialogoTexto
      open={false}
      onOpenChange={onOpenChange}
      titulo="Renombrar carpeta"
      valorInicial="Calle 13"
      onConfirmar={onConfirmar}
    />
  );

  // Reabre para OTRA carpeta, con otro valorInicial
  rerender(
    <DialogoTexto
      open
      onOpenChange={onOpenChange}
      titulo="Renombrar carpeta"
      valorInicial="Lote 3"
      onConfirmar={onConfirmar}
    />
  );

  await waitFor(() =>
    expect((screen.getByLabelText("Nombre") as HTMLInputElement).value).toBe("Lote 3")
  );
});

// H9: diferido del ledger. Con onConfirmar pendiente (no resuelve todavía), los
// botones quedan deshabilitados y el de confirmar avisa que está guardando.
test("mientras confirmar está en curso, los botones quedan deshabilitados y dice Guardando…", async () => {
  let resolver: () => void = () => {};
  const onConfirmar = vi.fn(
    () => new Promise<void>((resolve) => { resolver = resolve; })
  );
  abrir({ textoConfirmar: "Crear", onConfirmar });

  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "NP Peñón" } });
  fireEvent.click(screen.getByRole("button", { name: "Crear" }));

  const btnGuardando = await screen.findByRole("button", { name: "Guardando…" });
  expect(btnGuardando.hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Cancelar" }).hasAttribute("disabled")).toBe(true);

  resolver();
  await waitFor(() => expect(onConfirmar).toHaveBeenCalled());
});
