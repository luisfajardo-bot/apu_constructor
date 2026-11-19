import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import AvatarIngeniero, { type EstadoAvatar } from "./AvatarIngeniero";

const ESTADOS: EstadoAvatar[] = [
  "espera", "pensando", "buscando", "lista", "error", "deshabilitado",
];

test.each(ESTADOS)("el estado %s se expone en data-estado y en el aria-label", (e) => {
  render(<AvatarIngeniero estado={e} />);
  const img = screen.getByRole("img");
  expect(img.getAttribute("data-estado")).toBe(e);
  expect(img.getAttribute("aria-label")).toMatch(/agente/i);
});

test("cada estado tiene un aria-label distinto", () => {
  const etiquetas = new Set(ESTADOS.map((e) => {
    const { unmount } = render(<AvatarIngeniero estado={e} />);
    const l = screen.getByRole("img").getAttribute("aria-label");
    unmount();
    return l;
  }));
  expect(etiquetas.size).toBe(ESTADOS.length);
});
