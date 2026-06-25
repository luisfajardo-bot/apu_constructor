import { renderHook, act } from "@testing-library/react";
import { useDirtyRows } from "./useDirtyRows";

test("marca, cuenta y produce cambios; descarta", () => {
  const filas = [{ id: 1, precio: 100, fuente: "A" }, { id: 2, precio: 200, fuente: "B" }];
  const { result } = renderHook(() => useDirtyRows(filas));
  act(() => result.current.setCampo(1, "precio", 150));
  expect(result.current.count).toBe(1);
  expect(result.current.cambios()).toEqual([{ insumo_id: 1, precio: 150, fuente: "A" }]);
  act(() => result.current.descartar());
  expect(result.current.count).toBe(0);
});
