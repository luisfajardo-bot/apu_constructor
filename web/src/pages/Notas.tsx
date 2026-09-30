import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { listarTodasNotas } from "@/api/notas";
import { listarUsuarios } from "@/api/usuarios";
import type { Nota } from "@/lib/tipos";
import { DialogoNotas } from "@/components/notas/DialogoNotas";

const LIMIT = 100;
const fecha = (iso: string) => new Date(iso).toLocaleString("es-CO");

/** Todas las notas de la app (solo Admin). La ruta la protege RequiereRol y el
 *  endpoint /api/notas/todas exige admin: la pestaña no es la única puerta. */
export default function Notas() {
  const [entidad, setEntidad] = useState("");
  const [autor, setAutor] = useState("");
  const [autores, setAutores] = useState<{ id: string; label: string }[]>([]);
  const [inputQ, setInputQ] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<Nota[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [abierta, setAbierta] = useState<Nota | null>(null);

  // Mismo debounce que el buscador de Insumos: no consultar en cada tecla.
  useEffect(() => {
    const t = setTimeout(() => { setQ(inputQ.trim()); setOffset(0); }, 400);
    return () => clearTimeout(t);
  }, [inputQ]);

  // Las opciones del filtro de autor se cargan una vez; si falla, queda solo "Todos".
  useEffect(() => {
    listarUsuarios().then((us) => setAutores(
      us.map((u) => ({ id: u.user_id, label: u.nombre || u.email }))
        .sort((a, b) => a.label.localeCompare(b.label, "es"))
    )).catch(() => {});
  }, []);

  // Solo la última petición pinta: una respuesta vieja no pisa a la nueva.
  const seq = useRef(0);
  const cargar = useCallback(async () => {
    const mia = ++seq.current;
    setError(null);
    try {
      const r = await listarTodasNotas({ entidad, autor, q, limit: LIMIT, offset });
      if (mia !== seq.current) return;
      setItems(r.items);
      setTotal(r.total);
    } catch (e) {
      if (mia !== seq.current) return;
      setError(e instanceof Error ? e.message : "No se pudieron cargar las notas");
    }
  }, [entidad, autor, q, offset]);

  useEffect(() => { void cargar(); }, [cargar]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2">
        <h1 className="text-sm font-semibold">Notas</h1>
        <label className="ml-4 text-xs" htmlFor="notas-tipo">Tipo</label>
        <select id="notas-tipo" value={entidad}
                onChange={(e) => { setEntidad(e.target.value); setOffset(0); }}
                className="h-7 rounded border border-border bg-background px-2 text-xs">
          <option value="">Insumos y APUs</option>
          <option value="insumo">Insumos</option>
          <option value="apu">APUs</option>
        </select>
        <label className="ml-2 text-xs" htmlFor="notas-autor">Autor</label>
        <select id="notas-autor" value={autor}
                onChange={(e) => { setAutor(e.target.value); setOffset(0); }}
                className="h-7 rounded border border-border bg-background px-2 text-xs">
          <option value="">Todos los autores</option>
          {autores.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <Input className="h-7 w-64 text-xs" placeholder="Buscar en las notas…"
               value={inputQ} onChange={(e) => setInputQ(e.target.value)} />
        <span className="ml-auto text-xs text-muted-foreground">{total} nota(s)</span>
        <Button size="xs" variant="outline" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - LIMIT))}>‹ Ant.</Button>
        <Button size="xs" variant="outline" disabled={offset + LIMIT >= total}
                onClick={() => setOffset(offset + LIMIT)}>Sig. ›</Button>
      </div>
      {error && <div className="px-4 py-2 text-xs text-destructive">Error: {error}</div>}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-muted/80">
            <tr className="text-left text-muted-foreground">
              <th className="w-44 whitespace-nowrap border-b px-2 py-1.5 font-medium">Fecha</th>
              <th className="w-44 border-b px-2 py-1.5 font-medium">Autor</th>
              <th className="w-16 border-b px-2 py-1.5 font-medium">Tipo</th>
              <th className="w-80 border-b px-2 py-1.5 font-medium">De</th>
              <th className="border-b px-2 py-1.5 font-medium">Nota</th>
            </tr>
          </thead>
          <tbody>
            {items.map((n) => (
              <tr key={n.id} className="cursor-pointer hover:bg-muted/40"
                  onClick={() => setAbierta(n)}>
                <td className="whitespace-nowrap px-2 py-1 text-muted-foreground">{fecha(n.creada_en)}</td>
                <td className="truncate px-2 py-1">{n.autor_email}</td>
                <td className="px-2 py-1">{n.entidad === "apu" ? "APU" : "Insumo"}</td>
                <td className="max-w-[20rem] truncate px-2 py-1" title={n.etiqueta}>{n.etiqueta}</td>
                <td className="max-w-[32rem] truncate px-2 py-1" title={n.texto}>{n.texto}</td>
              </tr>
            ))}
            {items.length === 0 && !error && (
              <tr><td colSpan={5} className="px-2 py-6 text-center text-muted-foreground">
                No hay notas.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <DialogoNotas dueno={abierta?.dueno ?? null} etiqueta={abierta?.etiqueta ?? ""}
                    onClose={() => setAbierta(null)} onCambio={() => void cargar()} />
    </div>
  );
}
