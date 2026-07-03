import { useCallback, useEffect, useState, Fragment } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listarApus, getApuDetalle, type ListarApusParams } from "@/api/autoria";
import type { ApuResumen, ApuDetalle } from "@/lib/tipos";
import { cop } from "@/lib/moneda";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import { DialogoImportarApus } from "@/components/autoria/DialogoImportarApus";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";

const LIMIT = 100;

type EstadoExpansion = ApuDetalle | "cargando" | "error";

function clave(a: ApuResumen): string {
  return `${a.codigo}@@${a.turno}`;
}

export default function Apus() {
  const { perfil } = useAuth();
  const puedeEditar = puede(perfil?.rol, "editor");
  const [q, setQ] = useState("");
  const [inputQ, setInputQ] = useState("");
  const [turno, setTurno] = useState("");
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<ApuResumen[]>([]);
  const [total, setTotal] = useState(0);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [expandido, setExpandido] = useState<Record<string, EstadoExpansion | undefined>>({});
  const [agregarOpen, setAgregarOpen] = useState(false);
  const [importarOpen, setImportarOpen] = useState(false);
  const [editarDetalle, setEditarDetalle] = useState<ApuDetalle | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    setError(null);
    try {
      const params: ListarApusParams = { limit: LIMIT, offset };
      if (q) params.q = q;
      if (turno) params.turno = turno;
      const res = await listarApus(params);
      setItems(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setCargando(false);
    }
  }, [q, turno, offset]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Debounce de la búsqueda
  useEffect(() => {
    const t = setTimeout(() => {
      if (inputQ !== q) {
        setQ(inputQ);
        setOffset(0);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [inputQ, q]);

  function recargar() {
    // Colapsa expansiones y recarga (los detalles cacheados pueden quedar obsoletos)
    setExpandido({});
    cargar();
  }

  async function toggleExpand(a: ApuResumen) {
    const k = clave(a);
    if (expandido[k] !== undefined) {
      setExpandido((prev) => ({ ...prev, [k]: undefined }));
      return;
    }
    setExpandido((prev) => ({ ...prev, [k]: "cargando" }));
    try {
      const detalle = await getApuDetalle(a.codigo, a.turno);
      setExpandido((prev) => ({ ...prev, [k]: detalle }));
    } catch {
      setExpandido((prev) => ({ ...prev, [k]: "error" }));
    }
  }

  const hasPrev = offset > 0;
  const hasNext = offset + LIMIT < total;
  const page = Math.floor(offset / LIMIT) + 1;
  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const TOTAL_COLS = 7;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b">
        <h2 className="text-sm font-semibold">APUs</h2>
        {cargando && (
          <span className="text-xs text-muted-foreground animate-pulse">cargando…</span>
        )}
        {puedeEditar && (
          <div className="ml-auto flex gap-2">
            <Button size="xs" variant="outline" onClick={() => setAgregarOpen(true)}>
              Agregar APU
            </Button>
            <Button size="xs" variant="outline" onClick={() => setImportarOpen(true)}>
              Importar APUs
            </Button>
          </div>
        )}
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap gap-2 items-center px-3 py-2 border-b bg-muted/30">
        <Input
          className="h-7 w-56 text-xs"
          placeholder="Buscar código / nombre…"
          value={inputQ}
          onChange={(e) => setInputQ(e.target.value)}
        />
        <Select
          value={turno || "__all__"}
          onValueChange={(v) => {
            setTurno(v === "__all__" ? "" : v);
            setOffset(0);
          }}
        >
          <SelectTrigger size="sm" className="w-36 text-xs">
            <SelectValue placeholder="Todos los turnos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">Todos los turnos</SelectItem>
            <SelectItem value="DIURNO">DIURNO</SelectItem>
            <SelectItem value="NOCTURNO">NOCTURNO</SelectItem>
          </SelectContent>
        </Select>

        <span className="ml-auto text-xs text-muted-foreground">
          {total} APUs · pág. {page}/{totalPages}
        </span>
        <Button
          size="xs"
          variant="outline"
          disabled={!hasPrev}
          onClick={() => setOffset((o) => Math.max(0, o - LIMIT))}
        >
          ‹ Ant.
        </Button>
        <Button
          size="xs"
          variant="outline"
          disabled={!hasNext}
          onClick={() => setOffset((o) => o + LIMIT)}
        >
          Sig. ›
        </Button>
      </div>

      {error && (
        <div className="px-4 py-2 text-sm text-destructive border-b">Error: {error}</div>
      )}

      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-6 px-1" />
              <TableHead className="text-xs w-24">Código</TableHead>
              <TableHead className="text-xs w-20">Turno</TableHead>
              <TableHead className="text-xs">Nombre</TableHead>
              <TableHead className="text-xs w-14">Und</TableHead>
              <TableHead className="text-xs w-28">Grupo</TableHead>
              <TableHead className="text-xs w-16 text-right">N° comp.</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((a) => {
              const k = clave(a);
              const estado = expandido[k];
              const abierto = estado !== undefined;
              return (
                <Fragment key={k}>
                  <TableRow
                    className="hover:bg-muted/40 cursor-pointer"
                    onClick={() => toggleExpand(a)}
                  >
                    <TableCell className="w-6 px-1 py-1">
                      <span
                        aria-hidden
                        className="flex items-center justify-center w-5 h-5 text-muted-foreground"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 16 16"
                          fill="currentColor"
                          className={`w-3 h-3 transition-transform ${abierto ? "rotate-90" : ""}`}
                        >
                          <path
                            fillRule="evenodd"
                            d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L9.19 8 6.22 5.03a.75.75 0 0 1 0-1.06Z"
                            clipRule="evenodd"
                          />
                        </svg>
                      </span>
                    </TableCell>
                    <TableCell className="text-xs font-mono">{a.codigo}</TableCell>
                    <TableCell className="text-xs">{a.turno}</TableCell>
                    <TableCell className="text-xs max-w-[320px] truncate" title={a.nombre}>
                      {a.nombre}
                    </TableCell>
                    <TableCell className="text-xs">{a.unidad}</TableCell>
                    <TableCell className="text-xs text-muted-foreground truncate max-w-[7rem]" title={a.grupo}>
                      {a.grupo}
                    </TableCell>
                    <TableCell className="text-xs text-right font-mono tabular-nums">
                      {a.n_componentes}
                    </TableCell>
                  </TableRow>

                  {abierto && (
                    <TableRow
                      key={`exp-${k}`}
                      className="bg-muted/20 hover:bg-muted/20"
                    >
                      <TableCell colSpan={TOTAL_COLS} className="px-8 py-3">
                        {estado === "cargando" && (
                          <p className="text-xs text-muted-foreground py-2">cargando…</p>
                        )}
                        {estado === "error" && (
                          <p className="text-xs text-destructive py-2">
                            Error al cargar el detalle.
                          </p>
                        )}
                        {estado !== "cargando" && estado !== "error" && (
                          <DetalleApu
                            detalle={estado}
                            puedeEditar={puedeEditar}
                            onEditar={() => setEditarDetalle(estado)}
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
            {items.length === 0 && !cargando && (
              <TableRow>
                <TableCell
                  colSpan={TOTAL_COLS}
                  className="text-center text-xs text-muted-foreground py-6"
                >
                  No hay APUs.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {puedeEditar && (
        <>
          <DialogoAgregarApu
            open={agregarOpen}
            onOpenChange={setAgregarOpen}
            onCreado={recargar}
          />
          <DialogoImportarApus
            open={importarOpen}
            onOpenChange={setImportarOpen}
            onAplicado={recargar}
          />
          <DialogoAgregarApu
            key={editarDetalle ? `${editarDetalle.codigo}@@${editarDetalle.turno}` : "nuevo-edit"}
            open={editarDetalle !== null}
            onOpenChange={(v) => { if (!v) setEditarDetalle(null); }}
            onCreado={recargar}
            modo="editar"
            inicial={editarDetalle}
          />
        </>
      )}
    </div>
  );
}

function DetalleApu({
  detalle,
  puedeEditar,
  onEditar,
}: {
  detalle: ApuDetalle;
  puedeEditar: boolean;
  onEditar: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap text-xs">
        <span className="font-mono text-muted-foreground">
          APU: {detalle.codigo} · {detalle.turno}
        </span>
        <span className="text-muted-foreground truncate max-w-md">{detalle.nombre}</span>
        {puedeEditar && (
          <Button size="xs" variant="outline" className="ml-auto" onClick={onEditar}>
            Editar
          </Button>
        )}
      </div>

      <section>
        <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Composición costeada &mdash; costo unitario{" "}
          <span className="font-mono">{cop(detalle.costo_unitario)}</span>
        </h4>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Insumo</TableHead>
              <TableHead className="text-xs w-12">Und</TableHead>
              <TableHead className="text-xs w-16 text-right">Rend.</TableHead>
              <TableHead className="text-xs w-24 text-right">Precio</TableHead>
              <TableHead className="text-xs w-24 text-right">Costo</TableHead>
              <TableHead className="text-xs w-16">Cruce</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {detalle.composicion.map((lin, i) => (
              <TableRow key={`${lin.insumo_codigo}-${i}`}>
                <TableCell className="text-xs max-w-[220px] truncate" title={lin.insumo_nombre}>
                  {lin.insumo_nombre}
                </TableCell>
                <TableCell className="text-xs">{lin.unidad}</TableCell>
                <TableCell className="text-xs text-right font-mono tabular-nums">
                  {lin.rendimiento.toLocaleString("es-CO", { maximumFractionDigits: 4 })}
                </TableCell>
                <TableCell className="text-xs text-right font-mono tabular-nums">
                  {cop(lin.precio_unitario)}
                </TableCell>
                <TableCell className="text-xs text-right font-mono tabular-nums">
                  {cop(lin.costo)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {lin.calidad_cruce}
                </TableCell>
              </TableRow>
            ))}
            {detalle.composicion.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-xs text-muted-foreground py-3">
                  Sin componentes.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
