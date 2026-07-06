import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "./dialog";

// Regresión: el max-w del consumidor debe ganar; el base NO debe forzar sm:max-w-sm
// (que en desktop capaba el diálogo a 384px y dejaba los botones fuera de vista).
test("DialogContent respeta el max-w del consumidor y no fuerza max-w-sm", () => {
  render(
    <Dialog open>
      <DialogContent className="max-w-3xl">
        <DialogTitle>Prueba</DialogTitle>
        contenido
      </DialogContent>
    </Dialog>,
  );
  const content = document.querySelector('[data-slot="dialog-content"]');
  expect(content).not.toBeNull();
  const cls = content!.className;
  expect(cls).toContain("max-w-3xl");
  expect(cls).not.toContain("max-w-sm"); // el override que rompía el ancho ya no está
});

test("DialogContent limita la altura al viewport y deja el contenido desplazable", () => {
  render(
    <Dialog open>
      <DialogContent>
        <DialogTitle>Prueba</DialogTitle>
        contenido
      </DialogContent>
    </Dialog>,
  );
  const cls = document.querySelector('[data-slot="dialog-content"]')!.className;
  expect(cls).toContain("max-h-[calc(100dvh-2rem)]");
  expect(cls).toContain("overflow-y-auto");
});
