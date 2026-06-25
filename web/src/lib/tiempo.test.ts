// web/src/lib/tiempo.test.ts
import { fmtDuracion } from "@/lib/tiempo";

test("fmtDuracion formatea null, segundos y minutos", () => {
  expect(fmtDuracion(null)).toBe("—");
  expect(fmtDuracion(undefined)).toBe("—");
  expect(fmtDuracion(3210)).toBe("3.2 s");
  expect(fmtDuracion(65000)).toBe("1 m 05 s");
});
