import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ListFilter } from "lucide-react";
import { listarAuditoria, type EventoAuditoria } from "@/api/auditoria";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const ENTIDADES = ["", "insumo", "apu", "corrida", "usuario"] as const;

function fmtTs(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function resumen(v: Record<string, unknown> | null): string {
  if (!v) return "—";
  return Object.entries(v).map(([k, val]) => `${k}: ${val}`).join(", ");
}

type Fila = EventoAuditoria & { _loteId: string | null };

export default function Auditoria() {
  const [eventos, setEventos] = useState<EventoAuditoria[]>([]);
  const [cargando, setCargando] = useState(false);
  const [usuario, setUsuario] = useState("");
  const [accion, setAccion] = useState("");
  const [entidadTipo, setEntidadTipo] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [lotesAbiertos, setLotesAbiertos] = useState<Record<string, boolean>>({});

  const cargar = () => {
    setCargando(true);
    return listarAuditoria({
      user_id: usuario || undefined,
      accion: accion || undefined,
      entidad_tipo: entidadTipo || undefined,
      desde: desde || undefined,
      hasta: hasta || undefined,
      limit: 200,
    })
      .then((p) => setEventos(p.items))
      .catch((e) => toast.error(e instanceof Error ? e.message : "No se pudo cargar la auditoría."))
      .finally(() => setCargando(false));
  };

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Agrupa por lote_id: un lote con >1 fila se colapsa en una cabecera expandible.
  const filas = useMemo<Fila[]>(() => {
    const conteo = new Map<string, number>();
    eventos.forEach((e) => {
      const l = (e.contexto?.lote_id as string) || null;
      if (l) conteo.set(l, (conteo.get(l) ?? 0) + 1);
    });
    const out: Fila[] = [];
    for (const e of eventos) {
      const l = (e.contexto?.lote_id as string) || null;
      const esLote = l !== null && (conteo.get(l) ?? 0) > 1;
      out.push({ ...e, _loteId: esLote ? (l as string) : null });
    }
    return out;
  }, [eventos]);

  const toggleLote = (l: string) =>
    setLotesAbiertos((s) => ({ ...s, [l]: !s[l] }));

  const conteoPorLote = useMemo(() => {
    const m = new Map<string, number>();
    filas.forEach((f) => {
      if (f._loteId) m.set(f._loteId, (m.get(f._loteId) ?? 0) + 1);
    });
    return m;
  }, [filas]);

  const cabecerasEmitidas = new Set<string>();

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b">
        <h2 className="text-sm font-semibold">Auditoría</h2>
        {cargando && (
          <span className="text-xs text-muted-foreground animate-pulse">cargando…</span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Input
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            placeholder="user_id"
            className="h-7 w-36 text-xs"
          />
          <Input
            value={accion}
            onChange={(e) => setAccion(e.target.value)}
            placeholder="acción (p.ej. precio.editar)"
            className="h-7 w-52 text-xs"
          />
          <Select value={entidadTipo || "todas"} onValueChange={(v) => setEntidadTipo(v === "todas" ? "" : v)}>
            <SelectTrigger size="sm" className="h-7 w-32 text-xs">
              <SelectValue placeholder="entidad" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todas">todas</SelectItem>
              {ENTIDADES.filter(Boolean).map((e) => (
                <SelectItem key={e} value={e}>{e}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="date"
            value={desde}
            onChange={(e) => setDesde(e.target.value)}
            className="h-7 w-[8.5rem] text-xs"
            aria-label="Desde"
          />
          <span className="text-xs text-muted-foreground">→</span>
          <Input
            type="date"
            value={hasta}
            onChange={(e) => setHasta(e.target.value)}
            className="h-7 w-[8.5rem] text-xs"
            aria-label="Hasta"
          />
          <Button size="xs" variant="outline" onClick={() => cargar()}>
            <ListFilter data-icon="inline-start" />
            Filtrar
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-44">Fecha</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-48">Usuario</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-40">Acción</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-32">Entidad</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b">Antes → Después</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              if (f._loteId) {
                const primeraDelLote = !cabecerasEmitidas.has(f._loteId);
                if (primeraDelLote) cabecerasEmitidas.add(f._loteId);
                const abierto = !!lotesAbiertos[f._loteId];
                if (primeraDelLote) {
                  return (
                    <tr key={`h-${f._loteId}`} className="bg-muted/30">
                      <td colSpan={5} className="px-2 py-1.5">
                        <button
                          type="button"
                          className="flex items-center gap-2 font-medium hover:text-foreground"
                          onClick={() => toggleLote(f._loteId as string)}
                          aria-expanded={abierto}
                        >
                          <span className="text-muted-foreground w-3 inline-block text-center">
                            {abierto ? "▾" : "▸"}
                          </span>
                          <span>
                            {(f.contexto?.origen as string) || "lote"} — {conteoPorLote.get(f._loteId)} eventos
                          </span>
                          <Badge variant="outline">{f.accion}</Badge>
                        </button>
                        {!abierto && (
                          <span className="ml-6 text-muted-foreground">
                            {fmtTs(f.ts)} · {f.user_email ?? "sistema"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                }
                if (!abierto) return null;
              }
              return (
                <tr key={f.id} className="hover:bg-muted/40 even:bg-muted/10">
                  <td className="px-2 py-1 whitespace-nowrap text-muted-foreground">{fmtTs(f.ts)}</td>
                  <td className="px-2 py-1">
                    <span className="text-foreground">{f.user_email ?? "sistema"}</span>
                    <span className="text-muted-foreground"> · {f.rol}</span>
                  </td>
                  <td className="px-2 py-1"><Badge variant="secondary">{f.accion}</Badge></td>
                  <td className="px-2 py-1 text-muted-foreground">{f.entidad_tipo} #{f.entidad_id}</td>
                  <td className="px-2 py-1 text-muted-foreground truncate max-w-0">
                    {resumen(f.antes)} → {resumen(f.despues)}
                  </td>
                </tr>
              );
            })}
            {filas.length === 0 && !cargando && (
              <tr>
                <td colSpan={5} className="px-3 py-10 text-center text-muted-foreground text-sm">
                  Sin eventos de auditoría
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
