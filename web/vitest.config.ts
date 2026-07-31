/// <reference types="vitest" />
import path from "path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    // Valores de juguete para las envs de Supabase. `src/lib/supabase.ts` llama a
    // createClient() en tiempo de import y lanza "supabaseUrl is required" si faltan,
    // así que CUALQUIER test que importe (aun transitivamente) `@/api/client` no
    // colecta ni un caso. En la máquina del dev eso no se ve porque vitest carga
    // web/.env.local, que está en .gitignore: los tests pasaban en local y reventaban
    // en CI. Definirlas acá hace el run reproducible sin depender de ese archivo.
    // No apuntan a ningún proyecto real y ningún test sale a la red: los que ejercitan
    // auth siguen mockeando `@/lib/supabase`.
    env: {
      VITE_SUPABASE_URL: "http://localhost:54321",
      VITE_SUPABASE_ANON_KEY: "anon-key-de-prueba",
    },
  },
});
