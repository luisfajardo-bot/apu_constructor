import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      onAuthStateChange: vi.fn((cb: (e: string, s: unknown) => void) => {
        cb("SIGNED_IN", { access_token: "TOK", user: { email: "ana@obra.co" } });
        return { data: { subscription: { unsubscribe: vi.fn() } } };
      }),
      getSession: vi.fn(async () => ({ data: { session: { access_token: "TOK" } } })),
      signOut: vi.fn(async () => ({})),
    },
  },
}));
vi.mock("@/api/usuarios", () => ({
  getYo: vi.fn(async () => ({ email: "ana@obra.co", rol: "editor", nombre: "Ana" })),
}));

afterEach(() => vi.clearAllMocks());

import { AuthProvider, useAuth } from "./auth";

function Sonda() {
  const { perfil, cargando } = useAuth();
  return <div>{cargando ? "cargando" : perfil ? `rol:${perfil.rol}` : "anon"}</div>;
}

test("carga el perfil desde /api/yo tras SIGNED_IN", async () => {
  render(<AuthProvider><Sonda /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("rol:editor")).not.toBeNull());
});
