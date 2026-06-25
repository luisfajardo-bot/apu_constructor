import { parseSse } from "@/api/corridas";

test("parseSse interpreta un bloque progress", () => {
  const ev = parseSse('event: progress\ndata: {"i":3,"total":10,"descripcion":"X"}');
  expect(ev).toEqual({ event: "progress", data: { i: 3, total: 10, descripcion: "X" } });
});

test("parseSse interpreta un bloque done", () => {
  const ev = parseSse('event: done\ndata: {"id":7,"resumen":{}}');
  expect(ev?.event).toBe("done");
  expect((ev?.data as { id: number }).id).toBe(7);
});

test("parseSse devuelve null si no hay data", () => {
  expect(parseSse("event: progress")).toBeNull();
});
