import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  agregarLineas, importarLineas, previewLineas, descargarPlantillaLicitacion,
} from "@/api/corridas";
import { cop } from "@/lib/moneda";
import type { CorridaDetalle, LineaPreview, PreviewLineas } from "@/lib/tipos";

interface Props {
  open: boolean;
  corridaId: number;
  onOpenChange: (open: boolean) => void;
  onAgregado: (corrida: CorridaDetalle) => void;
}

type Via = "manual" | "excel";
type FaseExcel = "idle" | "cargando" | "preview" | "aplicando";

const CAMPO = "h-7 rounded border border-input bg-background px-2 text-xs";

export function DialogoAgregarLineas({ open, corridaId, onOpenChange, onAgregado }: Props) {
  const [via, setVia] = useState<Via>("manual");

  // --- línea a mano ---
  const [descripcion, setDescripcion] = useState("");
  const [unidad, setUnidad] = useState("");
  const [cantidad, setCantidad] = useState("1");
  const [precio, setPrecio] = useState("0");
  const [turno, setTurno] = useState("");
  const [guardando, setGuardando] = useState(false);

  // --- excel ---
  const fileRef = useRef<HTMLInputElement>(null);
  const archivoRef = useRef<File | null>(null);
  const [fase, setFase] = useState<FaseExcel>("idle");
  const [prev, setPrev] = useState<PreviewLineas | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setVia("manual");
    setDescripcion(""); setUnidad(""); setCantidad("1"); setPrecio("0"); setTurno("");
    setGuardando(false);
    setFase("idle"); setPrev(null); setErrorMsg(null);
    archivoRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }

  function cerrar(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function guardarManual() {
    const desc = descripcion.trim();
    if (!desc) return;
    setGuardando(true);
    try {
      const corrida = await agregarLineas(corridaId, [{
        descripcion: desc,
        unidad: unidad.trim(),
        cantidad: Number(cantidad) || 1,
        precio_contractual: Number(precio) || 0,
        ...(turno ? { shift: turno } : {}),
      }]);
      toast.success("Línea agregada");
      onAgregado(corrida);
      cerrar(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo agregar la línea.");
      setGuardando(false);
    }
  }

  async function elegirArchivo(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    archivoRef.current = archivo;
    setErrorMsg(null);
    setPrev(null);
    setFase("cargando");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      setPrev(await previewLineas(corridaId, form));
      setFase("preview");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error al leer el archivo");
      setFase("idle");
    }
  }

  async function aplicarExcel() {
    const archivo = archivoRef.current;
    if (!archivo || !prev) return;
    setFase("aplicando");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const corrida = await importarLineas(corridaId, form);
      toast.success(`${prev.total} ${prev.total === 1 ? "línea agregada" : "líneas agregadas"}`);
      onAgregado(corrida);
      cerrar(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo agregar las líneas.");
      setFase("preview");
    }
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaLicitacion();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  const pasadoDeTope = prev !== null && prev.total > prev.tope;

  return (
    <Dialog open={open} onOpenChange={cerrar}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-sm">Agregar líneas a la corrida</DialogTitle>
        </DialogHeader>

        <div className="flex gap-1">
          <Button size="xs" variant={via === "manual" ? "default" : "outline"}
                  onClick={() => setVia("manual")}>Una línea</Button>
          <Button size="xs" variant={via === "excel" ? "default" : "outline"}
                  onClick={() => setVia("excel")}>Desde Excel</Button>
        </div>

        {via === "manual" ? (
          <div className="flex flex-col gap-2">
            <label className="flex flex-col gap-0.5 text-xs">
              Descripción de la actividad
              <input aria-label="Descripción de la actividad" className={CAMPO}
                     value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
            </label>
            <div className="grid grid-cols-4 gap-2">
              <label className="flex flex-col gap-0.5 text-xs">
                Unidad
                <input aria-label="Unidad" className={CAMPO} value={unidad}
                       onChange={(e) => setUnidad(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Cantidad
                <input aria-label="Cantidad" className={CAMPO} type="number" min="0" value={cantidad}
                       onChange={(e) => setCantidad(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Precio contractual
                <input aria-label="Precio contractual" className={CAMPO} type="number" min="0"
                       value={precio} onChange={(e) => setPrecio(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Turno
                <select aria-label="Turno" className={CAMPO} value={turno}
                        onChange={(e) => setTurno(e.target.value)}>
                  <option value="">El de la corrida</option>
                  <option value="DIURNO">DIURNO</option>
                  <option value="NOCTURNO">NOCTURNO</option>
                </select>
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              La línea se arma con el mismo matcher que la corrida: queda por revisar y
              se le confirma o cambia el APU desde la tabla.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              Subí un Excel con <span className="font-semibold">solo las actividades que
              faltaron</span>, con las mismas columnas de la lista de licitación. El turno
              (DIURNO/NOCTURNO) es obligatorio por línea.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={elegirArchivo}
                disabled={fase === "cargando" || fase === "aplicando"}
                className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
              />
              {fase === "cargando" && (
                <span className="text-xs text-muted-foreground animate-pulse">leyendo…</span>
              )}
              <Button size="sm" variant="outline" type="button" onClick={bajarPlantilla}
                      className="ml-auto">
                <Download className="mr-1 h-3.5 w-3.5" />
                Descargar plantilla
              </Button>
            </div>

            {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

            {prev && (
              <div className="flex flex-col gap-3">
                <TablaPrev titulo={`Se agregan (${prev.nuevas.length})`} filas={prev.nuevas} />
                {prev.duplicadas.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold text-amber-700">
                      {prev.duplicadas.length === 1
                        ? "1 actividad ya está en la corrida"
                        : `${prev.duplicadas.length} actividades ya están en la corrida`}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Se agregan igual, como líneas nuevas. Si no las querés, sacalas del
                      Excel y volvé a subirlo.
                    </p>
                    <TablaPrev titulo="" filas={prev.duplicadas} conExistente />
                  </div>
                )}
                {pasadoDeTope && (
                  <p className="text-xs text-destructive">
                    El archivo trae {prev.total} líneas y el máximo por vez es {prev.tope}.
                    Partilo en varios archivos.
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => cerrar(false)}
                  disabled={guardando || fase === "aplicando"}>
            Cancelar
          </Button>
          {via === "manual" ? (
            <Button size="sm" onClick={guardarManual}
                    disabled={guardando || descripcion.trim() === ""}>
              {guardando ? "Agregando…" : "Agregar la línea"}
            </Button>
          ) : (
            <Button size="sm" onClick={aplicarExcel}
                    disabled={fase !== "preview" || prev === null || prev.total === 0 || pasadoDeTope}>
              {fase === "aplicando"
                ? "Agregando…"
                : `Agregar ${prev?.total ?? 0} ${prev?.total === 1 ? "línea" : "líneas"}`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TablaPrev({ titulo, filas, conExistente = false }: {
  titulo: string; filas: LineaPreview[]; conExistente?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {titulo && <p className="text-xs font-semibold">{titulo}</p>}
      {filas.length === 0 ? (
        <p className="text-xs text-muted-foreground">Ninguna.</p>
      ) : (
        <div className="max-h-52 overflow-auto rounded border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-2 py-1 text-left font-medium">Ítem</th>
                <th className="px-2 py-1 text-left font-medium">Descripción</th>
                <th className="px-2 py-1 text-left font-medium">Und</th>
                <th className="px-2 py-1 text-right font-medium">Cantidad</th>
                <th className="px-2 py-1 text-right font-medium">Contractual</th>
                <th className="px-2 py-1 text-left font-medium">Turno</th>
                {conExistente && <th className="px-2 py-1 text-left font-medium">Ya está</th>}
              </tr>
            </thead>
            <tbody>
              {filas.map((f, i) => (
                <tr key={`${f.item}-${i}`} className="border-t">
                  <td className="px-2 py-1 font-mono">{f.item}</td>
                  <td className="px-2 py-1">{f.descripcion}</td>
                  <td className="px-2 py-1">{f.unidad}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{f.cantidad}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{cop(f.precio_contractual)}</td>
                  <td className="px-2 py-1">{f.shift}</td>
                  {conExistente && (
                    <td className="px-2 py-1 text-muted-foreground">línea {f.seq_existente}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
