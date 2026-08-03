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
    // 10 s en vez de los 5 s por defecto: es margen para la CONTENCIÓN de máquina, no
    // para tapar cuelgues. Con 38 archivos jsdom en paralelo, las pantallas más pesadas
    // (Insumos, con tabla + filtros + diálogos) rozan el techo y fallan con
    // "Test timed out in 5000ms" ~1 de cada 18 corridas locales, sin que haya nada roto.
    // Se eligió 10 y no 15 a propósito: un test realmente colgado tiene que delatarse
    // rápido. Si un test necesita más de 10 s, el problema es el test, no este número.
    // Ojo: subir el timeout NO arregla causas concretas — el flake de Usuarios.test.tsx
    // era un `await import()` dentro del test que se comía 2 s del presupuesto, y eso se
    // arregló moviendo el import, no acá (ver el comentario en ese archivo).
    testTimeout: 10_000,
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
