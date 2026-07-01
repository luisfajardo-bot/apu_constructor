import { beforeAll, expect, test, vi } from "vitest";

beforeAll(() => {
  vi.stubEnv("VITE_SUPABASE_URL", "https://proj.supabase.co");
  vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key-test");
});

test("exporta un cliente supabase con auth", async () => {
  const { supabase } = await import("./supabase");
  expect(supabase).toBeDefined();
  expect(typeof supabase.auth.getSession).toBe("function");
});
