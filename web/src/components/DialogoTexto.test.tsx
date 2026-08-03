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
