import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ComponenteNuevo, Insumo, ApuDetalle } from "@/lib/tipos";
import { crearApu, editarApu } from "@/api/autoria";
import { listarInsumos } from "@/api/insumos";
import {
  rendimientoValido,
  hayRendimientoInvalido,
} from "@/lib/validacionApu";

interface DialogoAgregarApuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreado: () => void;
  modo?: "crear" | "editar";
  inicial?: ApuDetalle | null;
}

interface FilaComp {
  // id local para keys estables
  uid: number;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: string;
}

interface Cabecera {
  codigo: string;
  turno: string;
  nombre: string;
  unidad: string;
  grupo: string;
}

const CABECERA_VACIA: Cabecera = {
  codigo: "",
  turno: "DIURNO",
  nombre: "",
  unidad: "",
  grupo: "",
};

const inputCls =
  "h-8 w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";

let uidSeq = 1;
function nuevaFila(): FilaComp {
  return {
    uid: uidSeq++,
    insumo_codigo: "",
    insumo_nombre: "",
    unidad: "",
    rendimiento: "",
  };
}

export function DialogoAgregarApu({
  open,
  onOpenChange,
  onCreado,
  modo = "crear",
  inicial = null,
}: DialogoAgregarApuProps) {
  const [cab, setCab] = useState<Cabecera>(CABECERA_VACIA);
  const [filas, setFilas] = useState<FilaComp[]>([nuevaFila()]);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (modo === "editar" && inicial) {
      setCab({
        codigo: inicial.codigo,
        turno: inicial.turno,
        nombre: inicial.nombre,
        unidad: inicial.unidad,
        grupo: inicial.grupo,
      });
      setFilas(
        inicial.composicion.length === 0
          ? [nuevaFila()]
          : inicial.composicion.map((c) => ({
              uid: uidSeq++,
              insumo_codigo: c.insumo_codigo,
              insumo_nombre: c.insumo_nombre,
              unidad: c.unidad,
              rendimiento: String(c.rendimiento),
            })),
      );
    }
  }, [open, modo, inicial]);

  function setCabecera<K extends keyof Cabecera>(k: K, v: string) {
    setCab((prev) => ({ ...prev, [k]: v }));
  }

  function handleOpenChange(v: boolean) {
    if (!v) {
      setCab(CABECERA_VACIA);
      setFilas([nuevaFila()]);
      setGuardando(false);
    }
    onOpenChange(v);
  }

  function setFila(uid: number, parcial: Partial<FilaComp>) {
    setFilas((prev) => prev.map((f) => (f.uid === uid ? { ...f, ...parcial } : f)));
  }

  function quitarFila(uid: number) {
    setFilas((prev) => (prev.length <= 1 ? prev : prev.filter((f) => f.uid !== uid)));
  }

  // Componentes válidos: con insumo elegido y rendimiento > 0
  const compValidos: ComponenteNuevo[] = filas
    .filter((f) => f.insumo_codigo.trim() !== "" && rendimientoValido(f.rendimiento))
    .map((f) => ({
      insumo_codigo: f.insumo_codigo,
      rendimiento: Number(f.rendimiento),
      insumo_nombre: f.insumo_nombre || undefined,
      unidad: f.unidad || undefined,
    }));

  // Hay filas con insumo pero rendimiento inválido → bloquea y avisa
  const hayRendInvalido = hayRendimientoInvalido(filas);

  const cabeceraValida =
    cab.codigo.trim() !== "" &&
    cab.turno.trim() !== "" &&
    cab.nombre.trim() !== "" &&
    cab.unidad.trim() !== "" &&
    cab.grupo.trim() !== "";

  const valido = cabeceraValida && compValidos.length > 0 && !hayRendInvalido;

  async function guardar() {
    if (!valido) return;
    setGuardando(true);
    try {
      const payload = {
        nombre: cab.nombre.trim(),
        unidad: cab.unidad.trim(),
        grupo: cab.grupo.trim(),
        componentes: compValidos,
      };
      if (modo === "editar") {
        await editarApu(cab.codigo, cab.turno, payload);
        toast.success(`APU ${cab.codigo} (${cab.turno}) actualizado`);
      } else {
        await crearApu({ codigo: cab.codigo.trim(), turno: cab.turno, ...payload });
        toast.success(`APU ${cab.codigo.trim()} (${cab.turno}) creado`);
      }
      handleOpenChange(false);
      onCreado();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al guardar el APU";
      toast.error(msg);
      setGuardando(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-sm">
            {modo === "editar" ? "Editar APU" : "Agregar APU"}
          </DialogTitle>
        </DialogHeader>

        {/* Cabecera */}
        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Código</span>
            <input
              className={inputCls}
              value={cab.codigo}
              onChange={(e) => setCabecera("codigo", e.target.value)}
              autoFocus
              disabled={modo === "editar"}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Turno</span>
            <select
              className={inputCls}
              value={cab.turno}
              onChange={(e) => setCabecera("turno", e.target.value)}
              disabled={modo === "editar"}
            >
              <option value="DIURNO">DIURNO</option>
              <option value="NOCTURNO">NOCTURNO</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Unidad</span>
            <input
              className={inputCls}
              value={cab.unidad}
              onChange={(e) => setCabecera("unidad", e.target.value)}
            />
          </label>
          <label className="col-span-2 flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Nombre</span>
            <input
              className={inputCls}
              value={cab.nombre}
              onChange={(e) => setCabecera("nombre", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Grupo</span>
            <input
              className={inputCls}
              value={cab.grupo}
              onChange={(e) => setCabecera("grupo", e.target.value)}
            />
          </label>
        </div>

        {/* Composición */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs font-semibold">Composición</p>
            <Button
              size="xs"
              variant="outline"
              onClick={() => setFilas((prev) => [...prev, nuevaFila()])}
            >
              + Agregar fila
            </Button>
          </div>
          <div className="border rounded overflow-visible">
            <table className="w-full text-xs border-collapse">
              <thead className="bg-muted/60">
                <tr>
                  <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b">
                    Insumo
                  </th>
                  <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-14">
                    Und
                  </th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-28">
                    Rendimiento
                  </th>
                  <th className="px-2 py-1 border-b w-8" />
                </tr>
              </thead>
              <tbody>
                {filas.map((f) => {
                  const rendMal =
                    f.insumo_codigo.trim() !== "" && !rendimientoValido(f.rendimiento);
                  return (
                    <tr key={f.uid} className="align-top">
                      <td className="px-2 py-1 border-b">
                        <BuscadorInsumo
                          codigo={f.insumo_codigo}
                          nombre={f.insumo_nombre}
                          onElegir={(ins) =>
                            setFila(f.uid, {
                              insumo_codigo: ins.codigo,
                              insumo_nombre: ins.nombre,
                              unidad: ins.unidad,
                            })
                          }
                        />
                      </td>
                      <td className="px-2 py-1 border-b text-muted-foreground">
                        {f.unidad || "—"}
                      </td>
                      <td className="px-2 py-1 border-b">
                        <input
                          className={`${inputCls} text-right ${rendMal ? "border-destructive" : ""}`}
                          type="number"
                          min="0"
                          step="any"
                          value={f.rendimiento}
                          onChange={(e) =>
                            setFila(f.uid, { rendimiento: e.target.value })
                          }
                          aria-invalid={rendMal}
                        />
                      </td>
                      <td className="px-2 py-1 border-b text-center">
                        <button
                          type="button"
                          aria-label="Quitar fila"
                          onClick={() => quitarFila(f.uid)}
                          disabled={filas.length <= 1}
                          className="text-muted-foreground hover:text-destructive disabled:opacity-30"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {hayRendInvalido && (
            <p className="text-xs text-destructive mt-1">
              El rendimiento de cada insumo elegido debe ser mayor que 0.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={guardando}
          >
            Cancelar
          </Button>
          <Button size="sm" onClick={guardar} disabled={!valido || guardando}>
            {guardando
              ? modo === "editar"
                ? "Guardando…"
                : "Creando…"
              : modo === "editar"
                ? "Guardar cambios"
                : "Crear APU"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Buscador de insumo (autocompletado) ───────────────────────────────────────

interface BuscadorInsumoProps {
  codigo: string;
  nombre: string;
  onElegir: (ins: Insumo) => void;
}

function BuscadorInsumo({ codigo, nombre, onElegir }: BuscadorInsumoProps) {
  const [q, setQ] = useState("");
  const [resultados, setResultados] = useState<Insumo[]>([]);
  const [abierto, setAbierto] = useState(false);
  const [buscando, setBuscando] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Cerrar al hacer clic fuera
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setAbierto(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Debounce búsqueda
  useEffect(() => {
    if (q.trim() === "") {
      setResultados([]);
      return;
    }
    let cancelado = false;
    setBuscando(true);
    const t = setTimeout(async () => {
      try {
        const res = await listarInsumos({ q: q.trim(), limit: 15 });
        if (!cancelado) {
          setResultados(res.items);
          setAbierto(true);
        }
      } catch {
        if (!cancelado) setResultados([]);
      } finally {
        if (!cancelado) setBuscando(false);
      }
    }, 250);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [q]);

  function elegir(ins: Insumo) {
    onElegir(ins);
    setQ("");
    setResultados([]);
    setAbierto(false);
  }

  return (
    <div ref={boxRef} className="relative">
      {codigo ? (
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[11px] rounded bg-muted px-1.5 py-0.5">
            {codigo}
          </span>
          <span className="truncate max-w-[16rem]" title={nombre}>
            {nombre}
          </span>
          <button
            type="button"
            className="ml-auto text-[11px] text-muted-foreground hover:text-foreground underline"
            onClick={() => {
              setQ("");
              setAbierto(true);
            }}
          >
            cambiar
          </button>
        </div>
      ) : (
        <input
          className={inputCls}
          placeholder="Buscar insumo por código / nombre…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => {
            if (resultados.length > 0) setAbierto(true);
          }}
        />
      )}

      {abierto && !codigo && (
        <div className="absolute z-20 mt-1 w-full max-h-52 overflow-auto rounded border bg-popover shadow-md">
          {buscando && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">buscando…</p>
          )}
          {!buscando && resultados.length === 0 && q.trim() !== "" && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">
              Sin resultados
            </p>
          )}
          {resultados.map((ins) => (
            <button
              key={ins.id}
              type="button"
              onClick={() => elegir(ins)}
              className="flex w-full items-baseline gap-2 px-2 py-1 text-left text-xs hover:bg-muted"
            >
              <span className="font-mono text-[11px] text-muted-foreground">
                {ins.codigo}
              </span>
              <span className="truncate">{ins.nombre}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">
                {ins.unidad}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
