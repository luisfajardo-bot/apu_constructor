import { describe, expect, it } from "vitest";
import {
  consultaMencion, etiquetaDe, insertarMencion, mencionesVigentes, partesConMenciones,
} from "./menciones";

describe("menciones", () => {
  it("etiquetaDe usa el nombre y, si no hay, el email", () => {
    expect(etiquetaDe({ nombre: "Ana Ruiz", email: "a@o.co" })).toBe("Ana Ruiz");
    expect(etiquetaDe({ nombre: "", email: "a@o.co" })).toBe("a@o.co");
  });

  it("consultaMencion detecta la @ justo antes del cursor", () => {
    expect(consultaMencion("hola @an", 8)).toEqual({ inicio: 5, q: "an" });
    expect(consultaMencion("@", 1)).toEqual({ inicio: 0, q: "" });
    expect(consultaMencion("correo a@b", 10)).toBeNull();       // @ pegada a una palabra
    expect(consultaMencion("@ana listo", 10)).toBeNull();       // ya hay espacio después
    expect(consultaMencion("sin arroba", 10)).toBeNull();
  });

  it("insertarMencion reemplaza la consulta por @Etiqueta y un espacio", () => {
    expect(insertarMencion("hola @an", 5, 8, "Ana Ruiz")).toEqual({ texto: "hola @Ana Ruiz ", cursor: 15 });
    expect(insertarMencion("@b y más", 0, 2, "Beto")).toEqual({ texto: "@Beto  y más", cursor: 6 });
  });

  it("mencionesVigentes solo deja a los que siguen escritos en el texto", () => {
    const elegidos = [{ user_id: "u1", nombre: "Ana Ruiz" }, { user_id: "u2", nombre: "Beto" }];
    expect(mencionesVigentes("ojo @Ana Ruiz", elegidos)).toEqual(["u1"]);
    expect(mencionesVigentes("@Beto y @Ana Ruiz", elegidos)).toEqual(["u1", "u2"]);
    expect(mencionesVigentes("nadie", elegidos)).toEqual([]);
  });

  it("partesConMenciones separa los @Nombre para resaltarlos", () => {
    expect(partesConMenciones("hola @Ana Ruiz, mira", ["Ana Ruiz"])).toEqual([
      { texto: "hola ", mencion: false },
      { texto: "@Ana Ruiz", mencion: true },
      { texto: ", mira", mencion: false },
    ]);
    expect(partesConMenciones("sin nada", ["Ana"])).toEqual([{ texto: "sin nada", mencion: false }]);
    // el nombre más largo gana: "@Ana Ruiz" no se parte en "@Ana" + " Ruiz"
    expect(partesConMenciones("@Ana Ruiz", ["Ana", "Ana Ruiz"])).toEqual([{ texto: "@Ana Ruiz", mencion: true }]);
  });
});
