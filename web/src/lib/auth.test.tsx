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
import { supabase } from "@/lib/supabase";
import { getYo } from "@/api/usuarios";

function Sonda() {
  const { perfil, cargando } = useAuth();
  return <div>{cargando ? "cargando" : perfil ? `rol:${perfil.rol}` : "anon"}</div>;
}

test("carga el perfil desde /api/yo tras SIGNED_IN", async () => {
  render(<AuthProvider><Sonda /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("rol:editor")).not.toBeNull());
});

function SondaNoAutorizado() {
  const { noAutorizado, cargando } = useAuth();
  return <div>{cargando ? "cargando" : noAutorizado ? "no-autorizado" : "ok"}</div>;
}

test("noAutorizado permanece true tras el signOut disparado por un 403 de /api/yo", async () => {
  vi.mocked(getYo).mockRejectedValue(new Error("403"));
  let callback: ((e: string, s: unknown) => void) | undefined;
  vi.mocked(supabase.auth.onAuthStateChange).mockImplementation(
    (cb: (e: string, s: unknown) => void) => {
      callback = cb;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    },
  );
  // El signOut() real de Supabase re-dispara este mismo listener con sesión null;
  // lo simulamos aquí para reproducir esa causalidad (signOut ocurre dentro del catch).
  vi.mocked(supabase.auth.signOut).mockImplementation(async () => {
    callback?.("SIGNED_OUT", null);
    return {} as never;
  });

  render(<AuthProvider><SondaNoAutorizado /></AuthProvider>);
  callback?.("SIGNED_IN", { access_token: "TOK", user: { email: "ana@obra.co" } });

  await waitFor(() => expect(screen.getByText("no-autorizado")).not.toBeNull());
});
