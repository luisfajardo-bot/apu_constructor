import { render, screen, act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArmadoVivoProvider, useArmadoVivo } from "@/lib/armado";

// La lista elegida al crear la corrida (CorridasInicio) se fija de por vida: la
// pantalla de la corrida (Corrida.tsx) muestra un placeholder mientras se arma en
// vivo, y ese placeholder debe reflejar la lista real elegida, no quedar en blanco.
vi.mock("@/api/corridas", () => ({
  crearCorridaStream: vi.fn(
    async (
      _form: FormData,
      _onProgress: (p: unknown) => void,
      onStarted?: (c: { id: number; total: number }) => void,
    ) => {
      onStarted?.({ id: 7, total: 1 });
      return { id: 7, resumen: {} };
    },
  ),
  crearSampleStream: vi.fn(),
}));

function Sonda() {
  const vivo = useArmadoVivo();
  return <div data-testid="sonda">{String(vivo.listaId)}|{vivo.listaNombre}</div>;
}

function Disparador({ lista }: { lista?: { id: number; nombre: string } }) {
  const { armarArchivo } = useArmadoVivo();
  return (
    <button onClick={() => armarArchivo(new FormData(), () => {}, lista)}>
      Armar
    </button>
  );
}

describe("ArmadoVivoProvider — lista de precios elegida", () => {
  it("por defecto (sin lista) expone null/Principal", () => {
    render(
      <ArmadoVivoProvider>
        <Sonda />
      </ArmadoVivoProvider>,
    );
    expect(screen.getByTestId("sonda").textContent).toBe("null|Principal");
  });

  it("propaga la lista elegida al iniciar el armado en vivo", async () => {
    render(
      <ArmadoVivoProvider>
        <Disparador lista={{ id: 2, nombre: "NP Calle 13" }} />
        <Sonda />
      </ArmadoVivoProvider>,
    );
    await act(async () => {
      screen.getByRole("button", { name: /armar/i }).click();
    });
    expect(screen.getByTestId("sonda").textContent).toBe("2|NP Calle 13");
  });
});
