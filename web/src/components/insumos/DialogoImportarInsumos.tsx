import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import type { ImportInsumosUpsertPreview, ImportConflicto } from "@/lib/tipos";
import {
  previewImportarInsumos, aplicarImportarInsumos, descargarPlantillaInsumos,
} from "@/api/insumos";
import { cop } from "@/lib/moneda";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  listaId: number;
  listaNombre: string;
  fuentes: string[];
  onAplicado: () => void;
}

type Estado =
  | { fase: "idle" }
  | { fase: "cargando" }
  | { fase: "preview"; prev: ImportInsumosUpsertPreview }
  | { fase: "aplicando" };

export function DialogoImportarInsumos({ open, onOpenChange, listaId, listaNombre, fuentes, onAplicado }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const archivoRef = useRef<File | null>(null);
  const [estado, setEstado] = useState<Estado>({ fase: "idle" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [fuente, setFuente] = useState("");
  // La fuente con la que se corrió el preview vigente: es la que se manda al aplicar,
  // para que no se pueda aplicar con una declaración distinta a la que se vio.
  const fuentePreviewRef = useRef("");
  // Los insumo_id de los conflictos que el usuario decidió aplicar igual. Es estado del
  // cliente: marcar NO re-dispara el preview, solo viaja al aplicar.
  const [forzados, setForzados] = useState<Set<number>>(new Set());

  function resetear() {
    setEstado({ fase: "idle" });
    setErrorMsg(null);
    setFuente("");
    fuentePreviewRef.current = "";
    archivoRef.current = null;
    setForzados(new Set());
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleOpenChange(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function correrPreview(archivo: File, f: string) {
    setErrorMsg(null);
    setEstado({ fase: "cargando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("lista_id", String(listaId));
      form.append("fuente_import", f);
      const prev = await previewImportarInsumos(form);
      fuentePreviewRef.current = f;
      // Ninguna casilla arranca marcada: el servidor NO decide qué se aplica. Medida
      // contra el catálogo real, cualquier regla de pre-marcado marcaba materiales
      // distintos (`CLASE A` vs `CLASE B` al 93.8%). La comodidad la da el orden.
      setForzados(new Set());
      setEstado({ fase: "preview", prev });
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Error al procesar el archivo");
      setEstado({ fase: "idle" });
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    archivoRef.current = archivo;
    await correrPreview(archivo, fuente.trim());
  }

  // El preview depende de la fuente declarada (decide qué queda protegido), así que
  // cambiarla con un archivo ya elegido obliga a recalcularlo. Va en el blur y no en
  // cada tecla: es un input de texto con datalist.
  function handleFuenteBlur() {
    const f = fuente.trim();
    if (!f || !archivoRef.current || f === fuentePreviewRef.current) return;
    void correrPreview(archivoRef.current, f);
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaInsumos();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const archivo = archivoRef.current;
    if (!archivo) return;
    setEstado({ fase: "aplicando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("lista_id", String(listaId));
      form.append("fuente_import", fuentePreviewRef.current);
      forzados.forEach((id) => form.append("forzar_ids", String(id)));
      const res = await aplicarImportarInsumos(form);
      const errCount = res.errores?.length ?? 0;
      const protegidos = res.protegidos ?? 0;
      const invalidos = res.invalidos ?? 0;
      const resumen = `${res.creados} creado(s), ${res.actualizados} actualizado(s)` +
        (protegidos > 0 ? `, ${protegidos} protegido(s)` : "") +
        (invalidos > 0 ? `, ${invalidos} sin precio (no se aplicaron)` : "");
      if (errCount === 0) toast.success(resumen);
      else toast.warning(`${resumen}, ${errCount} error(es): ` +
        res.errores.map((er) => `${er.codigo}: ${er.error}`).join("; "));
      handleOpenChange(false);
      onAplicado();
    } catch (e: unknown) {
      toast.error(`No se pudo aplicar: ${e instanceof Error ? e.message : "error"}`);
      setEstado({ fase: "idle" });
    }
  }

  const enPreview = estado.fase === "preview";
  const enAplicando = estado.fase === "aplicando";
  const prev = enPreview ? estado.prev : null;
  const nAcciones = prev ? prev.crear.length + prev.actualizar.length + forzados.size : 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-sm">Importar insumos (crear + actualizar precios)</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          Con nombre: crea el insumo o, si ya existe, actualiza su precio. Sin nombre: solo
          actualiza el precio por código.
        </p>
        <p className="text-xs text-muted-foreground">
          Se importará sobre la lista <span className="font-semibold">{listaNombre}</span>.
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="fuente-import" className="text-xs font-medium">
            Fuente de esta importación
          </label>
          <input
            id="fuente-import"
            type="text"
            list="fuentes-import-list"
            value={fuente}
            onChange={(e) => setFuente(e.target.value)}
            onBlur={handleFuenteBlur}
            disabled={enAplicando}
            placeholder="PRECIO IDU"
            className="h-7 rounded border border-border bg-background px-2 text-xs"
          />
          <datalist id="fuentes-import-list">
            {fuentes.map((f) => <option key={f} value={f} />)}
          </datalist>
        </div>
        <p className="text-xs text-muted-foreground">
          Queda rotulada en todas las filas del archivo. Si declaras una fuente pública
          (PRECIO IDU), los precios internos no se tocan.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            disabled={!fuente.trim() || estado.fase === "cargando" || enAplicando}
            className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
          />
          {estado.fase === "cargando" && (
            <span className="text-xs text-muted-foreground animate-pulse">procesando…</span>
          )}
          <Button size="sm" variant="outline" type="button" onClick={bajarPlantilla}
                  disabled={enAplicando} className="ml-auto">
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
        </div>

        {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

        {prev && (
          <div className="space-y-3">
            <Seccion titulo="Crear">
              <Tabla cols={["Código", "Nombre", "Und", "Grupo", "Precio", "Fuente"]}
                     filas={prev.crear.map((f) => [f.codigo, f.nombre, f.unidad, f.grupo, cop(f.precio), f.fuente])} />
            </Seccion>
            <Seccion titulo="Actualizar precio">
              <Tabla cols={["Código", "Nombre", "Precio actual", "Precio nuevo", "Fuente actual", "Fuente nueva"]}
                     filas={prev.actualizar.map((c) => [c.codigo, c.nombre, cop(c.precio_actual), cop(c.precio_nuevo), c.fuente_actual || "—", c.fuente_nueva])} />
            </Seccion>
            {/* Ámbar en el título: es la única sección que declara que algo NO se tocó,
                y sin señal propia se pierde entre las otras seis, que se ven idénticas. */}
            <Seccion titulo="Protegidas — no se tocan (precio interno)"
                     className="text-amber-700 dark:text-amber-400">
              <Tabla cols={["Código", "Nombre", "Fuente actual", "Precio actual", "Precio del archivo"]}
                     filas={(prev.protegida ?? []).map((p) => [
                       p.codigo, p.nombre, p.fuente_actual || "(sin fuente)",
                       cop(p.precio_actual),
                       p.precio_archivo === null ? "—" : cop(p.precio_archivo)])} />
            </Seccion>
            <Seccion titulo="Ambiguas (código repetido, sin nombre)">
              <Tabla cols={["Código", "Candidatos"]}
                     filas={prev.ambigua.map((a) => [a.codigo, a.candidatos.map((c) => c.nombre).join(" · ")])} />
            </Seccion>
            <Seccion titulo="No encontradas (sin nombre, código inexistente)">
              <Tabla cols={["Código"]} filas={prev.no_encontrada.map((n) => [n.codigo])} />
            </Seccion>
            <SeccionConflictos conflictos={prev.conflicto ?? []} forzados={forzados}
                               onToggle={(id) => setForzados((s) => {
                                 const n = new Set(s);
                                 if (n.has(id)) n.delete(id); else n.add(id);
                                 return n;
                               })} />
            <Seccion titulo="Inválidas">
              <Tabla cols={["Código", "Nombre", "Motivo"]}
                     filas={prev.invalida.map((f) => [
                       f.codigo || "—",
                       f.nombre || "—",
                       f.motivo ?? "Falta el código.",
                     ])} />
            </Seccion>
          </div>
        )}

        {/* El aviso vive ADENTRO del footer, que es `sticky bottom-0`: con un preview de
            miles de filas la persona scrollea hasta acá para aplicar, y arriba del campo
            de fuente el aviso ya no se veía justo en el momento de decidir. Es la única
            protección contra una fuente pública mal escrita ("PRECIO IDU 2026" clasifica
            interno y el candado no se dispara), así que tiene que estar donde está el botón. */}
        <DialogFooter className="flex-col items-stretch sm:flex-col sm:items-stretch">
          {prev?.clasificacion_import && (
            <p role="status" className={`text-xs font-medium ${
              prev.clasificacion_import === "publico" ? "text-muted-foreground" : "text-amber-700 dark:text-amber-400"
            }`}>
              {prev.clasificacion_import === "publico"
                ? "Esta importación es PÚBLICA: no puede pisar precios internos."
                : <>Declaraste «{fuentePreviewRef.current}» y el sistema la clasifica como fuente INTERNA:
                    esta importación SÍ pisa los costos internos de la empresa. Si querías cargar la lista
                    pública del IDU, la fuente debe decir «<strong>PRECIO IDU</strong>», sin agregarle nada más.</>}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button size="sm" variant="outline" onClick={() => handleOpenChange(false)} disabled={enAplicando}>
              Cancelar
            </Button>
            <Button size="sm" onClick={aplicar} disabled={!enPreview || nAcciones === 0 || enAplicando || !fuente.trim()}>
              {enAplicando ? "Aplicando…" : `Aplicar (${nAcciones})`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Seccion({ titulo, className, children }:
                 { titulo: string; className?: string; children: React.ReactNode }) {
  return (
    <div>
      <p className={`text-xs font-semibold mb-1 ${className ?? ""}`}>{titulo}</p>
      {children}
    </div>
  );
}

function Tabla({ cols, filas }: { cols: string[]; filas: (string | number)[][] }) {
  if (filas.length === 0) return <p className="text-xs text-muted-foreground">Ninguno</p>;
  return (
    <div className="overflow-x-hidden overflow-y-auto max-h-52 border rounded">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1 text-left font-medium text-muted-foreground border-b align-bottom">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={i} className="hover:bg-muted/40 even:bg-muted/10">
              {fila.map((v, j) => (
                <td key={j} className="px-2 py-0.5 align-top break-words">{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeccionConflictos({ conflictos, forzados, onToggle }: {
  conflictos: ImportConflicto[];
  forzados: Set<number>;
  onToggle: (id: number) => void;
}) {
  const porCodigo = conflictos.filter((c) => c.insumo_id !== undefined);
  const porNombre = conflictos.filter((c) => c.insumo_id === undefined);

  return (
    <>
      <div>
        <p className="text-xs font-semibold mb-1">
          El código ya existe con otro nombre — marca los que sean el mismo insumo
        </p>
        {porCodigo.length > 0 && (
          // Ninguna viene marcada a propósito: el servidor no decide plata. El orden
          // (más parecido primero) es lo que hace que marcarlas no sea una cacería.
          <p className="text-xs text-muted-foreground mb-1">
            {porCodigo.length} fila(s), de más parecida a menos. Marca las que sean el
            mismo insumo.
          </p>
        )}
        {porCodigo.length === 0 ? <p className="text-xs text-muted-foreground">Ninguno</p> : (
          // Más alta que las otras tablas (`max-h-52`) a propósito: es la única en la que
          // la persona TRABAJA — las demás solo se leen. Y con nombres de licitación
          // reales, que pasan de 100 caracteres, cada fila ocupa 3-4 renglones: medido en
          // navegador, con 208px se veían 2 filas de 28, y la premisa de la feature es
          // marcar varias de corrido.
          <div className="overflow-x-hidden overflow-y-auto max-h-96 border rounded">
            <table className="w-full text-xs border-collapse">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                <tr>
                  {["", "Código", "Nombre en el archivo", "Nombre en tu base", "Parecido", "Precio actual", "Precio nuevo"].map((c, i) => (
                    <th key={i} className="px-2 py-1 text-left font-medium text-muted-foreground border-b align-bottom">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {porCodigo.map((c, i) => (
                  <tr key={i} className="hover:bg-muted/40 even:bg-muted/10">
                    <td className="px-2 py-0.5 align-top">
                      <input type="checkbox" aria-label={`Aplicar igual el ${c.codigo}`}
                             checked={forzados.has(c.insumo_id as number)}
                             onChange={() => onToggle(c.insumo_id as number)} />
                    </td>
                    <td className="px-2 py-0.5 align-top break-words">{c.codigo}</td>
                    <td className="px-2 py-0.5 align-top break-words">{c.nombre}</td>
                    <td className="px-2 py-0.5 align-top break-words">{c.nombre_actual}</td>
                    <td className="px-2 py-0.5 align-top">
                      {Math.round((c.parecido ?? 0) * 100)}%
                      {c.numeros_coinciden === false && (
                        <span className="block text-amber-700 dark:text-amber-400">
                          los números no coinciden
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-0.5 align-top">
                      {c.sin_precio_actual ? "sin tarifa" : cop(c.precio_actual ?? 0)}
                    </td>
                    <td className="px-2 py-0.5 align-top">{cop(c.precio ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Seccion titulo="En conflicto (no se crean)">
        <Tabla cols={["Código", "Nombre", "Motivo"]}
               filas={porNombre.map((c) => [c.codigo || "—", c.nombre || "—", c.motivo])} />
      </Seccion>
    </>
  );
}
